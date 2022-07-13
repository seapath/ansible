# Rollback a change with Seapath-debian

With Yocto, the upgrade process is using swupdate, by having 2 separate disk partitions. Seapath has an evolved process to manage an automatic rollback in case of failure, that change the "active" partition back to the original (known to be working) one.

The Seapath-debian way of doing things is quite different: it uses apt and lvm.
The upgrade process is the very standard "apt" way (apt update, apt upgrade, ...).
The rollback posibilities leverage [LVM snapshots](https://documentation.suse.com/sles/12-SP4/html/SLES-all/cha-lvm-snapshots.html).

That said, a classic way to upgrade would look like:

```
# create a snapshot for the root logical volume
lvcreate -L 1GB -s -n root_snap /dev/vg1/root 

# check it's working as it should
lvdisplay vg1/root_snap

# do the change, an upgrade for example
apt update
apt -y dist-upgrade
apt -y autoremove

# in case there is a problem, ROLLBACK
lvconvert --merge vg1/root_snap
reboot

# in case no rollback is deemed needed, remove the snapshot
lvremove -y vg1/root_snap
```
