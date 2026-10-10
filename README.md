# Local Disk Backup

A Home Assistant custom integration that registers a **backup agent** for a folder on a locally attached disk — a second internal drive or an external USB disk. Once set up, the disk appears as a normal location in **Settings → System → Backups**, alongside "Home Assistant Cloud" and any network storage. Automatic backups, manual backups, download and restore all work through the standard UI.

Installable through HACS as a custom repository.

---

## Yes, this integrates into the native backup page

Home Assistant 2025.1 introduced *backup agents*. Any integration can ship a `backup.py` that implements `async_get_backup_agents()`, and the core backup manager then offers it as a storage location. Google Drive, OneDrive and Synology DSM all work this way. There is no custom panel and no separate UI — this integration plugs into the one you already use.

---

## The part that actually takes work: making the disk visible

The integration writes to a path. The real question is whether Home Assistant can *see* that path, and the answer depends entirely on your installation method. **Read the section that matches your install before you install the integration.**

### Home Assistant Container / Core / Supervised

Easy. Mount the disk on the host, then expose it to Home Assistant.

```bash
# Host: find the disk and mount it persistently
lsblk -o NAME,SIZE,FSTYPE,UUID
sudo mkdir -p /mnt/backup_disk
# add to /etc/fstab, by UUID so it survives reordering:
#   UUID=xxxx-xxxx  /mnt/backup_disk  ext4  defaults,nofail  0  2
sudo mount -a
```

For Docker, add a bind mount to the Home Assistant container:

```yaml
services:
  homeassistant:
    volumes:
      - /mnt/backup_disk:/mnt/backup_disk
```

Then point the integration at `/mnt/backup_disk`. Make sure the directory is writable by the UID the container runs as (`chown`/`chmod` on the host).

### Home Assistant OS

Harder, and worth being honest about: **HAOS has no "add local disk" option in the UI.** Settings → System → Storage only offers network storage (SMB/CIFS and NFS), and the Home Assistant container can only see `/config`, `/media`, `/share`, `/ssl` and `/backup`.

The supported route is a udev rule delivered on a `CONFIG` USB stick — the CONFIG partition has a documented `udev/` folder that HAOS imports into `/etc/udev/rules.d` at startup. The rule mounts your labelled disk to `/mnt/data/supervisor/media/habackup`, which the HA container sees as `/media/habackup`.

**→ Full step-by-step in [`docs/HAOS-SETUP.md`](docs/HAOS-SETUP.md)**, including the mount-propagation gotcha that causes most "the drive shows up but is empty" reports, and a troubleshooting table.

The rule itself is [`docs/80-mount-habackup.rules`](docs/80-mount-habackup.rules). It matches on filesystem label rather than on bus, so it works for an internal SATA/NVMe disk and a USB one alike and cannot accidentally grab your boot drive.

Two alternatives: share the disk over SMB/NFS from another machine and use HAOS's built-in network storage (no custom integration needed at all), or *Move data disk* to relocate HA onto the bigger drive — supported and sensible, but not a backup.

### Checking what Home Assistant can see

Install the *Terminal & SSH* add-on and run:

```bash
ls -la /media /share
df -h /media/habackup
```

If your disk's mount point does not appear, or `df` reports your data partition's size rather than the disk's, the integration cannot use it yet.

---

## A note on disk space (Supervised / HAOS)

On Supervisor-based installs, Supervisor creates the backup in `/backup` first, and Home Assistant then streams it out to each configured agent. So a full backup briefly needs room on the **internal** disk too, even when the destination is your external drive. On Container/Core installs the stream goes straight through.

---

## Installation

### HACS (custom repository)

1. HACS → three-dot menu → **Custom repositories**
2. URL: `https://github.com/YOUR_GITHUB_USERNAME/ha-local-disk-backup`, category: **Integration**
3. Install, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Local Disk Backup**

### Manual

Copy `custom_components/local_disk_backup/` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

| Field | Meaning |
| --- | --- |
| **Folder path** | Absolute path as seen from inside Home Assistant, e.g. `/media/habackup`. Must already exist and be writable. |
| **Name** | What the location is called in the backup picker. |
| **Backups to keep** (options) | Prune to the N newest after each write. `0` keeps everything and lets Home Assistant's own retention settings decide. |

You can add the integration more than once to write to several disks.

After setup: **Settings → System → Backups → Automatic backups** → tick your disk under *Locations*. You can select several locations at once, which is the whole point — keep one copy local and one on the removable drive.

## What it creates on disk

```
/media/habackup/
├── 1a2b3c4d.tar              # the backup archive
└── 1a2b3c4d.metadata.json    # metadata, so listing doesn't unpack the tar
```

Writes go to a `.writing` temp file and are renamed into place only once complete, so an interrupted backup never looks like a valid one.

## Entities

Two diagnostic sensors per disk: **Free space** and **Backups stored**. Useful for an automation that warns you before the drive fills up, or when the disk has been unplugged — both go unavailable when the mount disappears.

## Limitations

- If the disk is not mounted when Home Assistant starts, setup retries rather than failing permanently. But Home Assistant will not mount it for you.
- Backups are stored unencrypted-at-rest in the sense that this integration adds no encryption of its own. Home Assistant's own backup encryption (the emergency kit passphrase) still applies if enabled.
- Restoring from this location works through the normal restore UI, but a bare-metal restore needs the disk reachable from the recovery environment — keep a copy somewhere else too.

## Development

The agent implements the `BackupAgent` interface from `homeassistant.components.backup`: `async_upload_backup`, `async_download_backup`, `async_list_backups`, `async_get_backup` and `async_delete_backup`, plus the `async_get_backup_agents` / `async_register_backup_agents_listener` module functions that the backup manager looks for. All filesystem work runs in the executor, and transfers are chunked at 4 MiB so multi-gigabyte backups do not sit in memory.

Minimum Home Assistant version: **2025.5** (for `BackupNotFound`; the code falls back gracefully on older cores, but 2025.1 is the floor for backup agents existing at all).

## License

MIT
