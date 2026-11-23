//! The keys (PROTOCOL.md "Pairing code" and part 2 "Machine keys and request authentication"):
//! - the admin's Ed25519 key: the signature over the policy and the commands, its fingerprint and pairing code;
//! - the X25519 box keys: the secret this machine shares with the admin, and from it the key that authenticates the
//!   machine's requests (mac_key) and the one that opens the secrets the admin seals for it (seal_key);
//! - the sha256 of the files.

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::ChaCha20Poly1305;
use ed25519_dalek::{Signature, VerifyingKey};
use hkdf::Hkdf;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use x25519_dalek::{PublicKey, StaticSecret};

/// HKDF's salt for both derived keys.
const HKDF_SALT: &[u8] = b"caramos-business/2";
/// A sealed blob starts with its 12-byte nonce.
const NONCE_LEN: usize = 12;

/// Lowercase hex of `bytes`.
pub fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        text.push(DIGITS[usize::from(byte >> 4)] as char);
        text.push(DIGITS[usize::from(byte & 0x0f)] as char);
    }
    text
}

pub fn sha256_hex(data: &[u8]) -> String {
    hex(&Sha256::digest(data))
}

/// The admin key from its base64 text (agent.json's `admin_key`, `GET /key`): a raw 32-byte Ed25519 public key.
pub fn decode_key(text: &str) -> Result<[u8; 32], String> {
    let bytes = STANDARD.decode(text).map_err(|_| "the admin key is not base64".to_string())?;
    <[u8; 32]>::try_from(bytes.as_slice()).map_err(|_| "the admin key is not 32 bytes long".to_string())
}

/// First 16 hex digits of sha256(key): what discovery answers carry to tell the admins apart.
pub fn fingerprint(key: &[u8]) -> String {
    sha256_hex(key)[..16].to_string()
}

/// The six digits the admin window shows while pairing is open:
/// `int.from_bytes(sha256(b"caramos-business-pairing:" + key)[:4], "big") % 1_000_000`.
/// The pairing itself is done by the Python helper; the agent's tests check that both sides agree.
pub fn pairing_code(key: &[u8]) -> String {
    let digest = Sha256::new().chain_update(b"caramos-business-pairing:").chain_update(key).finalize();
    let number = u32::from_be_bytes([digest[0], digest[1], digest[2], digest[3]]);
    format!("{:06}", number % 1_000_000)
}

/// Checks the base64 `signature` over `message` with the admin key. Strict verification: it also refuses
/// malleable signatures and weak keys.
pub fn verify(key: &[u8; 32], message: &[u8], signature: &str) -> Result<(), String> {
    let key = VerifyingKey::from_bytes(key).map_err(|_| "the admin key is not an Ed25519 key".to_string())?;
    let bytes = STANDARD.decode(signature).map_err(|_| "the signature is not base64".to_string())?;
    let signature = Signature::from_slice(&bytes).map_err(|_| "the signature is not 64 bytes long".to_string())?;
    key.verify_strict(message, &signature)
        .map_err(|_| "the signature does not match the admin key".to_string())
}

/// A 32-byte key from base64 (the box keys in the policy, in keys.json).
pub fn decode_key32(text: &str, what: &str) -> Result<[u8; 32], String> {
    let bytes = STANDARD.decode(text).map_err(|_| format!("{what} is not base64"))?;
    <[u8; 32]>::try_from(bytes.as_slice()).map_err(|_| format!("{what} is not 32 bytes long"))
}

/// The public half of an X25519 private key.
pub fn box_public(private: &[u8; 32]) -> [u8; 32] {
    PublicKey::from(&StaticSecret::from(*private)).to_bytes()
}

/// The two keys this machine and the admin share:
/// `secret = X25519(own private key, the other side's public key)`, then
/// `HKDF-SHA256(ikm = secret, salt = "caramos-business/2", info = "mac" or "seal", length = 32)`.
#[derive(Clone, PartialEq, Eq)]
pub struct SharedKeys {
    /// Authenticates every request of the paired machine.
    pub mac_key: [u8; 32],
    /// Opens the secrets sealed for the machine.
    pub seal_key: [u8; 32],
}

impl std::fmt::Debug for SharedKeys {
    fn fmt(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        formatter.write_str("SharedKeys(…)")
    }
}

impl SharedKeys {
    /// From one side's private box key and the other side's public one. A public key of low order, which would
    /// make the secret known to anyone, is refused.
    pub fn derive(own_private: &[u8; 32], other_public: &[u8; 32]) -> Result<SharedKeys, String> {
        let secret = StaticSecret::from(*own_private).diffie_hellman(&PublicKey::from(*other_public));
        if !secret.was_contributory() {
            return Err("the admin's box key is not a valid X25519 key".to_string());
        }
        Ok(SharedKeys { mac_key: hkdf(secret.as_bytes(), b"mac"), seal_key: hkdf(secret.as_bytes(), b"seal") })
    }

    /// `X-Caramos-Mac`: base64 of HMAC-SHA256(mac_key, METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIME + "\n" +
    /// hex(sha256(body))). The body is empty for GET; the path is the request target, query included.
    pub fn request_mac(&self, method: &str, path_with_query: &str, time: i64, body: &[u8]) -> String {
        let message = format!("{method}\n{path_with_query}\n{time}\n{}", sha256_hex(body));
        let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(&self.mac_key).expect("HMAC takes a key of any length");
        mac.update(message.as_bytes());
        STANDARD.encode(mac.finalize().into_bytes())
    }

    /// Opens a blob the admin sealed for `machine_id`: `base64(nonce || ChaCha20-Poly1305(seal_key, nonce, plaintext,
    /// aad = machine_id))`. Fails when it was sealed for another machine or changed on the way.
    pub fn unseal(&self, sealed: &str, machine_id: &str) -> Result<Vec<u8>, String> {
        let bytes = STANDARD.decode(sealed.trim()).map_err(|_| "the sealed secrets are not base64".to_string())?;
        if bytes.len() < NONCE_LEN + 16 {
            return Err("the sealed secrets are too short".to_string());
        }
        let (nonce, ciphertext) = bytes.split_at(NONCE_LEN);
        let cipher = ChaCha20Poly1305::new_from_slice(&self.seal_key).expect("the seal key is 32 bytes");
        cipher
            .decrypt(nonce.into(), Payload { msg: ciphertext, aad: machine_id.as_bytes() })
            .map_err(|_| "the sealed secrets do not open with this machine's key".to_string())
    }
}

fn hkdf(secret: &[u8], info: &[u8]) -> [u8; 32] {
    let mut key = [0u8; 32];
    Hkdf::<Sha256>::new(Some(HKDF_SALT), secret).expand(info, &mut key).expect("32 bytes is a valid HKDF-SHA256 length");
    key
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hex_digits() {
        assert_eq!(hex(&[0x00, 0x0f, 0xa5, 0xff]), "000fa5ff");
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn keys_must_be_32_bytes_of_base64() {
        assert!(decode_key("A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=").is_ok());
        assert!(decode_key("A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMQ==").is_err());
        assert!(decode_key("not base64!").is_err());
    }
}
