#!/bin/sh
# LVM snapshot rebooter : wait for any merging LV and reboot once done
# Use this it to workaround GRUB limitation : it does not handle LV with merging snapshot

PREREQ="lvm"
prereqs()
{
   echo "$PREREQ"
}

case $1 in
prereqs)
   prereqs
   exit 0
   ;;
esac

. /scripts/functions

# TIMEOUT=600 # How much time to wait for the merge to complete before panic'ing (empty/undef for unlimited)
# TODO make a proper config entry? (/conf/initramfs.conf)

if [ ! -x "/sbin/lvm" ]; then
   panic "lvs executable not found"
fi

is_lvm_snapshot_merging() {
	lv_merging_nb=$(/sbin/lvm lvs --select 'lv_merging!=0' | /usr/bin/wc -l)
	test $lv_merging_nb -ne 0
}

log_begin_msg "Starting LVM Snapshot rebooter"

# Wait for LVM elements to appear and be activated by udev
wait_for_udev 10

if is_lvm_snapshot_merging; then
	log_end_msg
	/sbin/lvm vgchange -a y
	log_begin_msg "Waiting for snapshot merging to complete..."
	count=0
	while is_lvm_snapshot_merging; do
		count=$(( count + 1 ))
		sleep 1
		if [ -n "$TIMEOUT" ] && [ "$count" -gt "$TIMEOUT" ]; then
			panic "Timeout while waiting for LVM snapshot merging!"
		fi
	done

	log_success_msg "Snapshot merging complete, rebooting..."
	sleep 3 # To allow display on console

	reboot -f # No init to handle reboot => -f
else
	log_success_msg "Done. (No LVM snapshot need merging)"
fi

exit 0

