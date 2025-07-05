# CI Restore snapshot via dd

This role restore a full LV using dd in the initramfs.

Setup (with dracut):

```
mkdir -p /usr/lib/dracut/modules.d/91restore

cat << 'EOF' > /usr/lib/dracut/modules.d/91restore/module-setup.sh
#!/bin/bash

check() {
    return 0
}

depends() {
    echo "lvm"
    return 0
}

install() {
    inst /bin/dd
    inst /bin/rm
    inst /bin/echo
    inst /bin/mount
    inst /bin/head
    inst /sbin/e2fsck
    inst /sbin/tune2fs
    inst /bin/umount
    inst /bin/sh
    inst /sbin/blkid
    inst /sbin/findfs || true

    inst_hook initqueue/finished 10 "$moddir/restore-check.sh"
}
EOF

cat << 'EOF' > /usr/lib/dracut/modules.d/91restore/restore-check.sh
#!/bin/sh

echo "[restore] restore-check.sh is running..." >> /run/initramfs/restore.log
echo "[restore] restore-check.sh is running..." > /dev/kmsg

if [ -z "$ESP_DEV" ]; then
	ESP_DEV=$(blkid | grep -i "EFI" | awk -F: '{print $1; exit}')
fi

echo "[restore] ESP_DEV=$ESP_DEV" >> /run/initramfs/restore.log
echo "[restore] ESP_DEV=$ESP_DEV" > /dev/kmsg

mkdir -p /mnt/esp
mount -o ro "$ESP_DEV" /mnt/esp 2>> /run/initramfs/restore.log

if [ -f /mnt/esp/RESTORE_PLZ ]; then
    echo "[restore] RESTORE_PLZ found, doing restore!" >> /run/initramfs/restore.log
    echo "[restore] RESTORE_PLZ found, doing restore!" > /dev/kmsg

    echo "lvm lvchange --setactivationskip y vg1/root-backup" >> /run/initramfs/restore.log
    echo "lvm lvchange --setactivationskip y vg1/root-backup" > /dev/kmsg
    lvm lvchange --setactivationskip n vg1/root-backup 2>&1
    lvm vgchange -aay vg1 >> /run/initramfs/restore.log 2>&1
    dd if=/dev/vg1/root-backup of=/dev/vg1/root bs=10M status=progress
    echo "lvm lvchange --setactivationskip n vg1/root-backup" >> /run/initramfs/restore.log
    echo "lvm lvchange --setactivationskip n vg1/root-backup" > /dev/kmsg
    lvm lvchange --setactivationskip y vg1/root-backup
    #e2fsck -f /dev/vg1/root
    #tune2fs -U 5d13a016-07ad-4cb6-9ec6-8d28f0324f13 /dev/vg1/root

    mount -o remount,rw "$ESP_DEV" /mnt/esp
    rm -f /mnt/esp/RESTORE_PLZ
    echo "[restore] RESTORE_PLZ removed." >> /run/initramfs/restore.log
    echo "[restore] RESTORE_PLZ removed." > /dev/kmsg
fi

umount /mnt/esp
EOF

chmod +x /usr/lib/dracut/modules.d/91restore/*.sh

dracut -f
```

Creating the snapshot:

```
lvcreate -s -n root-snap -L400M vg1/root
lvremove -y vg1/root-backup
lvcreate --yes -L $(lvs --noheadings --units b -o lv_size --nosuffix /dev/vg1/root | xargs)B -n root-backup vg1
dd if=/dev/vg1/root-snap of=/dev/vg1/root-backup bs=10M status=progress
lvremove -y vg1/root-snap
lvchange --setactivationskip y vg1/root-backup
```

## Requirements


## Role Variables


## Example Playbook

```yaml
- name: CI restore snapshot with dd in the initramfs
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_restoredd }
```
