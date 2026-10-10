# Setting this up on Home Assistant OS

HAOS has no "add a local disk" button. Settings → System → Storage only offers network storage (SMB/CIFS and NFS), and the Home Assistant container can only see `/config`, `/media`, `/share`, `/ssl` and `/backup` — all of which live on the data partition.

The supported way around it is a **udev rule delivered on a `CONFIG` USB stick**. This is a documented Home Assistant OS feature, not a hack: the CONFIG partition has a `udev/` folder whose contents HAOS imports into `/etc/udev/rules.d` at startup. Because the rule is re-imported from the stick on every boot, it survives OS updates.

You will need: your backup disk, plus one small USB stick for the CONFIG partition. (If the machine is short on ports, you can instead create a `CONFIG` folder inside the boot partition, but that means pulling the boot medium and editing it on another computer — the stick is easier.)

---

## Step 1 — Prepare the backup disk

On any other computer, give the disk **one ext4 partition** labelled exactly `HABACKUP`.

```bash
sudo mkfs.ext4 -L HABACKUP /dev/sdX1    # replace sdX1 with the real partition
```

Use ext4. exFAT and FAT32 carry no POSIX permissions, and NTFS needs the `ntfs3` driver — neither is worth the risk for backups.

This works the same whether the disk is an internal SATA/NVMe drive or an external USB one. The rule matches on the filesystem label, not on the bus, so it cannot accidentally grab your boot drive.

## Step 2 — Prepare the CONFIG stick

Format a small USB stick as FAT32 and set its label to exactly `CONFIG`. On it, create:

```
CONFIG/
└── udev/
    └── 80-mount-habackup.rules
```

Copy [`80-mount-habackup.rules`](80-mount-habackup.rules) into that `udev/` folder. **Save it with Unix (LF) line endings** — HAOS will ignore it otherwise, which is the single most common reason this step silently fails.

While you are there, it is worth also dropping an `authorized_keys` file (your SSH public key) at the root of the CONFIG stick. That enables HAOS debug SSH on port 22222, which is how you diagnose this if it doesn't work.

## Step 3 — Plug everything in and reboot

Attach the backup disk **and** the CONFIG stick, then reboot Home Assistant (Settings → System → three-dot menu → Restart Home Assistant → Reboot system).

**Reboot rather than hot-plug, and this matters more than it looks.** The container's `/media` is a bind mount of the host's `/mnt/data/supervisor/media`. A filesystem mounted *inside* that directory after the container started does not propagate into the container — you get a directory that looks right from the host but appears empty from Home Assistant. That's the cause of nearly every "the drive shows up in Media but there are no files" report you'll find in the forums. The mount has to exist before the container starts.

Same rule applies later: if you ever unplug and re-attach the disk, restart Home Assistant afterwards.

## Step 4 — Verify

Install the **Terminal & SSH** add-on and run:

```bash
ls -la /media
df -h /media/habackup
touch /media/habackup/write-test && rm /media/habackup/write-test && echo "writable"
```

You want to see `habackup` listed, `df` reporting the size of the backup disk (not the size of your data partition), and the write test passing. If `df` reports your data partition's size, the mount didn't propagate — reboot.

## Step 5 — Install the integration

HACS → Custom repositories → add the repo as an **Integration** → install → restart Home Assistant → Settings → Devices & Services → **Add Integration** → **Local Disk Backup** → path `/media/habackup`.

Then Settings → System → Backups → Automatic backups → tick the new location.

---

## If it doesn't work

Re-run the config import without rebooting, from the Terminal & SSH add-on:

```bash
ha os import
```

Then check from debug SSH on port 22222 (`ssh root@<ip> -p 22222`):

```bash
ls -la /etc/udev/rules.d/          # is the rule there?
lsblk -o NAME,LABEL,FSTYPE,SIZE    # is the label exactly HABACKUP?
systemctl list-units --type=mount  # did the mount unit start?
journalctl -b | grep -i habackup
```

Common causes, in the order they usually bite:

| Symptom | Cause |
| --- | --- |
| Rule not in `/etc/udev/rules.d` | Stick not labelled exactly `CONFIG`, or the file has CRLF line endings |
| Mount unit never starts | Filesystem label isn't exactly `HABACKUP`, or the partition isn't ext4 |
| `/media/habackup` exists but is empty from HA | Mount propagation — reboot |
| Permission denied writing | Filesystem isn't ext4, or the directory is owned by a different UID |

## Two alternatives worth considering

**Share the disk from another machine over SMB or NFS.** If the drive doesn't strictly have to live in the HA box, this needs no custom integration and no udev at all — HAOS supports network storage for backups natively, in the UI. It is genuinely the lowest-maintenance option.

**Move the data disk** (Settings → System → Storage → Move data disk) relocates all of Home Assistant onto the bigger drive. Fully supported, and a sensible thing to do — but it is *not* a backup. One disk is still one point of failure. Use it alongside this, not instead of it.

## A note on free space

On HAOS, Supervisor builds the backup in `/backup` on the internal data partition first, and Home Assistant then streams it out to each configured agent. So a full backup still needs temporary room on the **internal** disk even though the destination is your external drive. Worth checking if your boot medium is a small SD card or eMMC.
