//! Local accounts and their groups, for the files that only one user may read (PROTOCOL.md part 3, "Inboxes and
//! per-user files" and "Helpdesk tickets"): such a file is root's with the user's primary group, mode 0640, which
//! keeps it from everyone else only when that group is the user's alone. That is CaramOS's default (adduser makes one
//! group per user); for other users the daemon writes no ticket file and leaves their inbox readable by all.
//!
//! Accounts come from /etc/passwd, and from `getent` for directory users; groups from /etc/group, and from `getent`.

use std::fs;

use crate::sections::System;

/// A login name with its uid and primary gid.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Account {
    pub name: String,
    pub uid: u32,
    pub gid: u32,
}

/// A group: its name, gid and the members /etc/group lists.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Group {
    pub name: String,
    pub gid: u32,
    pub members: Vec<String>,
}

/// One line of /etc/passwd or of `getent passwd`: `name:x:uid:gid:gecos:home:shell`.
pub fn parse_passwd_line(line: &str) -> Option<Account> {
    let fields: Vec<&str> = line.trim_end().split(':').collect();
    if fields.len() < 4 || fields[0].is_empty() || !crate::status::valid_login(fields[0]) {
        return None;
    }
    Some(Account { name: fields[0].to_string(), uid: fields[2].parse().ok()?, gid: fields[3].parse().ok()? })
}

/// One line of /etc/group or of `getent group`: `name:x:gid:member,member`.
pub fn parse_group_line(line: &str) -> Option<Group> {
    let fields: Vec<&str> = line.trim_end().split(':').collect();
    if fields.len() < 3 || fields[0].is_empty() {
        return None;
    }
    let members = fields.get(3).map_or_else(Vec::new, |list| list.split(',').filter(|name| !name.is_empty()).map(str::to_string).collect());
    Some(Group { name: fields[0].to_string(), gid: fields[2].parse().ok()?, members })
}

fn local_accounts(system: &System) -> Vec<Account> {
    fs::read_to_string(system.path("/etc/passwd")).unwrap_or_default().lines().filter_map(parse_passwd_line).collect()
}

fn local_groups(system: &System) -> Vec<Group> {
    fs::read_to_string(system.path("/etc/group")).unwrap_or_default().lines().filter_map(parse_group_line).collect()
}

fn getent(system: &System, database: &str, key: &str) -> Option<String> {
    if !system.commands {
        return None;
    }
    let output = system.run("getent", &[database, key], std::time::Duration::from_secs(10)).ok()?;
    output.success().then(|| output.stdout.lines().next().unwrap_or_default().to_string())
}

/// The account of a login name, local or from the directory.
pub fn by_name(system: &System, name: &str) -> Option<Account> {
    if !crate::status::valid_login(name) {
        return None;
    }
    local_accounts(system)
        .into_iter()
        .find(|account| account.name == name)
        .or_else(|| getent(system, "passwd", name).as_deref().and_then(parse_passwd_line).filter(|account| account.name == name))
}

/// The account of a uid, local or from the directory.
pub fn by_uid(system: &System, uid: u32) -> Option<Account> {
    local_accounts(system)
        .into_iter()
        .find(|account| account.uid == uid)
        .or_else(|| getent(system, "passwd", &uid.to_string()).as_deref().and_then(parse_passwd_line).filter(|account| account.uid == uid))
}

fn group(system: &System, gid: u32) -> Option<Group> {
    local_groups(system)
        .into_iter()
        .find(|group| group.gid == gid)
        .or_else(|| getent(system, "group", &gid.to_string()).as_deref().and_then(parse_group_line).filter(|group| group.gid == gid))
}

/// The account's primary gid when that group is the user's own: it has the user's name, /etc/group lists no members
/// for it, and no other account has it as its primary group. Else why not.
pub fn private_group(system: &System, account: &Account) -> Result<u32, String> {
    let Some(group) = group(system, account.gid) else {
        return Err(format!("{}: its primary group {} does not exist", account.name, account.gid));
    };
    if group.name != account.name {
        return Err(format!("{}: its primary group {} is not its own", account.name, group.name));
    }
    if !group.members.is_empty() {
        return Err(format!("{}: its group {} lists members", account.name, group.name));
    }
    if let Some(other) = local_accounts(system).into_iter().find(|other| other.gid == account.gid && other.name != account.name) {
        return Err(format!("{}: {} has the same primary group", account.name, other.name));
    }
    Ok(account.gid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn private_groups() {
        let root = crate::testutil::TempDir::new("accounts");
        fs::create_dir_all(root.path().join("etc")).unwrap();
        fs::write(
            root.path().join("etc/passwd"),
            "root:x:0:0:root:/root:/bin/bash\nlan:x:1001:1001:Lan,,,:/home/lan:/bin/bash\nminh:x:1002:100::/home/minh:/bin/bash\n\
             binh:x:1003:1003::/home/binh:/bin/bash\nkhach:x:1004:1003::/home/khach:/bin/bash\nhoa:x:1005:1005::/home/hoa:/bin/bash\n",
        )
        .unwrap();
        fs::write(root.path().join("etc/group"), "root:x:0:\nusers:x:100:\nlan:x:1001:\nbinh:x:1003:\nhoa:x:1005:lan\n").unwrap();
        let system = System::test(root.path());
        let lan = by_name(&system, "lan").unwrap();
        assert_eq!((lan.uid, lan.gid), (1001, 1001));
        assert_eq!(by_uid(&system, 1001).unwrap().name, "lan");
        assert_eq!(private_group(&system, &lan), Ok(1001));
        let refused = |name: &str| private_group(&system, &by_name(&system, name).unwrap()).unwrap_err();
        assert!(refused("minh").contains("is not its own"), "users");
        assert!(refused("binh").contains("khach has the same primary group"));
        assert!(refused("hoa").contains("lists members"));
        assert_eq!(by_name(&system, "nobody-here"), None);
        assert_eq!(by_name(&system, "bad/name"), None);
        assert_eq!(parse_group_line("sudo:x:27:caram,lan").unwrap().members, ["caram", "lan"]);
    }
}
