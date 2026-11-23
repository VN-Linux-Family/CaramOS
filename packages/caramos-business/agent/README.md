# caramos-business-agent

The employee machine's agent of CaramOS Doanh nghiệp, in Rust: one binary, `caramos-business-agent` (0.3.0). It
follows [../PROTOCOL.md](../PROTOCOL.md): part 2 for 0.2, part 3 for 0.3; part 1's and part 2's "Agent" sections say
how it reads the points left open, and part 3's "Changes during implementation" lists where 0.3 differs from the
contract as first written.

- `daemon`: the service, as root. Fetches the admin's signed policy (format 2), checks it against the admin key pinned
  at pairing, writes this machine's effective settings for the session parts, applies the system sections (browser,
  printers, power, apps, usb, firewall, wifi, shared, snapshots), runs the signed commands that `/wait` brings, and
  reports back: check-in with health, inventory when it is on, results, help requests. Every request but `/hello`
  carries an HMAC made with the machine's box key. From 0.3:
  - waits while the admin has not approved the machine (`approval.json`), asking for the policy every minute;
  - on a signed removal notice puts everything back (ufw too), forgets the pairing, writes `removed.json` and disables
    itself; a 410 only makes it fetch the policy;
  - fetches the machine's signed tickets when their version moves, writes each user's `tickets/<uid>.json`
    (root's with the user's own group, 0640) and tells the users what changed;
  - freezes the machine (overlayroot, the GRUB maintenance entry), masks the update timers in each frozen boot,
    restarts into the maintenance entry at the maintenance time (`overlayroot-chroot grub-reboot`), runs the
    maintenance boot (policy, updates, apps, then a frozen boot again), and finishes a frozen machine's leave in its
    next unfrozen boot;
  - writes Timeshift's settings for `snapshots` and takes a snapshot before `update`;
  - unseals the remote help session's key for the session part, and keeps inboxes readable by their user only.
- `session`: in each user's session. Applies the user's sections (wallpaper, folders, shares, screen_lock), shows
  what the daemon relays (messages, countdowns, the remote help request and banner, through `caramos-business
  --prompt`; ticket updates through `notify-send`), runs remote help (stunnel with the session's pre-shared key),
  shows `--prompt frozen` at each login on a frozen machine, and writes the user's status (with `screen_lock_on`).
- `leave`: as root, when the machine leaves the company. Stops the service and puts back everything the agent
  changed; the users' part through their session parts. On a frozen machine it takes the freeze and a leave marker
  onto the disk and prints `reboot needed`: the next boot finishes there.

## Build and test

No Rust toolchain is needed on the host, only Docker:

```sh
./build.sh          # cargo-1.85 test, then cargo-1.85 build --release → target/release/caramos-business-agent
./build.sh shell    # a shell in the build container (with the network)
./build.sh vendor   # fetch the crates of Cargo.lock into vendor/ again (needs the network)
```

`build.sh` builds the image `caramos-business-agent-build` once from `Dockerfile.build`: Ubuntu 24.04 with
`cargo-1.85` and `rustc-1.85`, the toolchain of the Launchpad PPA build. It mounts `packages/caramos-business` (the
tests read `../tests/protocol-examples`) and builds with `--network none --offline --locked`, as on Launchpad.
Clippy is not in that image; it runs clean in a throwaway container with Ubuntu's `rust-1.85-clippy`
(`PATH=/usr/lib/rust-1.85/bin:$PATH cargo clippy --offline --locked --all-targets`, `CARGO_TARGET_DIR` outside the
mounted tree).

For the Debian package: Build-Depends `cargo-1.85, rustc-1.85`; in `agent/`, `cargo-1.85 build --release --offline
--locked` (and `cargo-1.85 test --offline --locked`); install `target/release/caramos-business-agent` as
`/usr/lib/caramos-business/caramos-business-agent`. `.cargo/config.toml` points crates.io at `vendor/`.

The tests (149): 118 unit tests; `tests/protocol_examples.rs` (part 1's shared examples, and format 1 refused now);
`tests/protocol_v2.rs` (every v2 vector: keys and derived keys, MACs, the sealed blob, the signed policy and both
effective settings, each invalid policy refused for its reason, each signed command decided); `tests/protocol_v3.rs`
(the v3 vectors of the agent: the MACs of `GET /policy` and `/files`, the policy with `shared` and `snapshots` and
both effective settings, each invalid policy, the freeze refused next to a tidy, the remote help command and its
sealed key, the removal notices, the tickets, the origins from `apt-cache policy`, the inventory and health keys, the
capabilities, and the exact files the agent writes); `tests/service_round.rs` (rounds against a stand-in admin on
127.0.0.1 that checks every MAC, GETs included: approval, removal notice, tickets, commands from `/wait`, `leave`).

`tests/standin_admin.py` is a stand-in admin for VM tests, with the v2 test keys (never for anything real):
`serve STATE`, `machine STATE --url URL --name NAME [--pending]` (a pairing: agent.json and agent-box.key to copy to
the machine), `approve`, `remove` (a signed removal notice), `policy STATE POLICY.json [--secrets S.json]` (fills in
format, serial, admin_box_key, the sealed secrets and the files), `command STATE ACTION ARGS [--machines ID,…|
--departments ID,…] [--psk-file F]` (seals a remote help key), `ticket` (makes or changes a ticket). It checks every
MAC, answers 403 pending and 410 as 0.3 does, and leaves out of `/wait` the commands a machine answered. Each request
it receives goes to `STATE/log/<kind>.jsonl`.

## Dependencies

Pinned in `Cargo.lock` (55 packages, MSRV ≤ 1.85, resolver 3) and vendored in `vendor/` (54 crates, 27 MB), which is
committed as `cargo vendor` wrote it: each crate's `.cargo-checksum.json` lists every file, so the source package must
ship `vendor/` whole. `agent/.gitignore` keeps the repository's `build/` and `*.log` rules from dropping vendored
files.

| Crate | Version | Why |
|---|---|---|
| serde, serde_json | 1.0.219, 1.0.140 | JSON; the last versions on `syn` 2, so `syn` is vendored once |
| ed25519-dalek | 2.2.0, no features | signature check only |
| x25519-dalek | 2.0.1, `static_secrets` only | the machine box key; shares curve25519-dalek 4.1.3 with ed25519-dalek |
| hkdf, hmac | 0.12.4, 0.12.1 | the mac and seal keys, request MACs; on digest 0.10 with sha2 |
| chacha20poly1305 | 0.10.1, `alloc` only | opening the machine's sealed secrets (no RNG: decryption only) |
| sha2 | 0.10.9 | file and key hashes, the inventory's hash |
| base64 | 0.22.1 | keys, signatures, MACs, sealed blobs |
| ureq | 2.12.1, no default features | plain HTTP, no TLS |

`idna_adapter` is pinned to 1.0.0, its back end without Unicode tables: ureq's `url` crate would otherwise bring
ICU4X (20 crates), and the admin is an IPv4 address. `libc` and `fiat-crypto` (10 MB of `vendor/`) are dependencies
for other targets that amd64 never builds.

To change a dependency: `./build.sh shell`, move `.cargo/config.toml` aside, `cargo-1.85 update -p <crate>
--precise <version>`, put the file back, then `./build.sh vendor` and `./build.sh`.

## Layout

| File | |
|---|---|
| `src/main.rs` | the `daemon`, `session` and `leave` subcommands |
| `src/daemon.rs` | the service: rounds, approval, removal, discovery when the admin moved, `/wait`, tickets, commands, relay, scheduler, maintenance, `leave` |
| `src/session.rs` | the session part's rounds, status, notice, end of session |
| `src/protocol.rs` | ports, paths, MACHINE, USER_STATUS, check-in, envelopes, results, discovery datagrams |
| `src/policy.rs`, `src/settings.rs` | format 2: parsing, validation, departments and overrides merged; the sections |
| `src/commands.rs` | signed commands: checks, actions, `commands.json` |
| `src/crypto.rs` | signatures, fingerprint, pairing code, X25519 and HKDF keys, MACs, sealed secrets |
| `src/store.rs` | atomic writes, agent.json, the box key, the stored policy and files, effective.json |
| `src/fetch.rs` | HTTP to the admin, with the MAC headers |
| `src/discovery.rs`, `src/machine.rs` | UDP discovery; MACHINE: host name, route address and card, edition, version |
| `src/sections/` | the daemon's sections and `managed.json`: browser, printers, power, apps, usb, firewall, wifi; `shared.rs` (guest session, freeze, maintenance window), `snapshots.rs` (Timeshift) |
| `src/tickets.rs`, `src/accounts.rs` | the tickets: checks, per-user files, what changed; accounts and the private-group rule |
| `src/inventory.rs`, `src/health.rs` | the inventory and the health of the check-in |
| `src/relay.rs`, `src/inbox.rs` | the relay: the daemon's inboxes and pending results; the session part's side |
| `src/prompt.rs` | `caramos-business --prompt KIND`, its answer, closing it |
| `src/remotehelp.rs` | consent, stunnel client, x11vnc, banner |
| `src/screenlock.rs`, `src/shares.rs` | the session part's `screen_lock` and `shares` |
| `src/status.rs` | USER_STATUS files, written by the session part, read by the service |
| `src/wallpaper.rs`, `src/folders.rs`, `src/userdirs.rs`, `src/tidy.rs` | part 1's wallpaper and folders |
| `src/clock.rs`, `src/process.rs`, `src/logging.rs` | Vietnam's time, running tools with time limits, logs |

## How the parts are started

`/lib/systemd/system/caramos-business-agent.service` (the package's), enabled by the root helper after pairing: root,
`Restart=on-failure`, `PrivateTmp=true`, and no `ProtectSystem` or `ProtectHome`, which 0.2's sections cannot run
under (PROTOCOL.md part 2, "The service unit" under "Files"). It logs to the journal (`journalctl -u caramos-business-agent`).

`/etc/xdg/autostart/caramos-business-session.desktop` runs `caramos-business-agent session` in every session; it
applies settings only while `/etc/caramos-business/role` says `employee`, agent.json exists and a policy is stored.
It logs to `~/.xsession-errors`, ends with the login session, and a newer instance for the same user replaces an
older one.

What the agent keeps:

- root: `/etc/caramos-business/agent.json` and `agent-box.key` (from the helper); in
  `/var/lib/caramos-business/agent/`: `policy.json`, `files/`, `effective.json` (0644, for the session parts),
  `managed.json` (0600, what to put back), `commands.json` (0600), `approval.json`, `removed.json`,
  `maintenance.json`, `leave-pending.json` (0644), `tickets/` (`version` 0600, `<uid>.json` root:<group> 0640);
  `/run/caramos-business/inbox/<uid>/` (the relay: root:<group> 0750, entries 0640); `/run/nologin` during a
  maintenance boot.
- each user: `~/.config/caramos-business/state.json` (wallpaper, launchers copied, bookmarks added, screen lock
  values before, notice) and `user-dirs.local`; `~/.local/share/caramos-business/server/` (the folder links);
  `$XDG_RUNTIME_DIR/caramos-business/`: `status.json`, `session.pid`, `taken`, `frozen-told`, `outbox/`,
  `remote-help/` (stunnel's configuration and the 0600 key file, while it runs).

Tools it runs: `gsettings`, `xfconf-query`, `gio` with GVfs, `notify-send`, `nemo-desktop`/`xfdesktop`,
`cinnamon-screensaver-command`, `xflock4`, `loginctl`, `systemctl`, `lpadmin`/`lpstat`, `ufw`, `nmcli`, `udevadm`,
`rtcwake`, `apt-get`, `apt-cache`, `caramos-ota`, App Center's helper, `flatpak`, `dpkg`, `lsblk`, `findmnt`,
`du`, `ip`, `getent`; `update-grub`, `overlayroot-chroot` (with `rm`, `tee` and `grub-reboot`) and `timeshift`;
`dmidecode` and `smartctl` when installed; `stunnel4` and `x11vnc` for remote help; and the Python window:
`caramos-business --prompt KIND …` and `--connect <smb://host/share>`.
