# Installation process
text
reboot
#cdrom

# localization
lang en_US
keyboard --xlayouts='fr'
timezone Europe/Paris --utc

# System bootloader configuration
bootloader --append="quiet crashkernel=1G-4G:192M,4G-64G:256M,64G-:512M  console=ttyS0,115200 efi=runtime ipv6.disable=1 inst.wait_for_network=1"

# Disks and partitions
# UPDATE: Change device path for your correct installation disk
ignoredisk --only-use=/dev/vda
# Clear the Master Boot Record
zerombr
# Partition clearing information
clearpart --all --initlabel

# Disk partitioning information
reqpart --add-boot
# UPDATE: Change device path for your correct installation disk
part pv.0 --fstype=lvmpv --ondisk=/dev/vda  --size=18000
part /boot/efi --fstype=efi --ondisk=/dev/vda --size=512 --asprimary
volgroup vg1 --pesize=4096 pv.0
logvol / --vgname=vg1 --name=root --fstype=ext4 --size=10000
logvol /var/log --vgname=vg1 --name=varlog --fstype=ext4 --size=2000
logvol swap --vgname=vg1 --name=swap --fstype=swap --size=500


# Network information
# UPDATE: change device name and static IP to your correct settings (gateway and nameserver might also be needed)
network --device=enp1s0 --bootproto=static --ip=10.10.10.201 --netmask=255.255.255.0 --gateway=10.10.10.1 --nameserver=8.8.8.8 --hostname=testol --onboot=yes

# Do not configure the X Window System
skipx

# system services
services --disabled=corosync,pacemaker,NetworkManager,firewalld
services --enabled=openvswitch

# Users
# UPDATE: The password is "toto" for all users
user --uid=1000 --gid=1000 --groups=wheel --name=virtu --iscrypted --password="$6$BZGBti/HRUWlyHhY$8zI5CFPcuBJw7pKupU4d9QLTqphBDyDpkW8zMySquiKO/qcRZoEcqvCJraJXJ5y0sdNdJ2vHb6.z/UvvLJSrM/"

user --uid=1005 --gid=1005 --groups=wheel,haclient --name=ansible --iscrypted --password="$6$BZGBti/HRUWlyHhY$8zI5CFPcuBJw7pKupU4d9QLTqphBDyDpkW8zMySquiKO/qcRZoEcqvCJraJXJ5y0sdNdJ2vHb6.z/UvvLJSrM/"

user --uid=902 --gid=902  --name=oraclelinux-snmp

rootpw  --iscrypted $6$2Aj/yELlJst1TZMM$3JVT2YYjrbMpNGoHs.2O.SvcbtGSZqQvz5Ot5CdDmU/IsRFASnSqmlvS8bg8eGoOHmQ5i7dak0VWQWtziqYjh0


# ssh keys
# UPDATE: input your ssh-keys for
sshkey --username=virtu "ssh-rsa XXX"
sshkey --username=ansible "ssh-rsa XXX"
sshkey --username=root "ssh-rsa XXX"

# adding needed repositories

repo --name="ol9_AppStream" --baseurl="https://yum.oracle.com/repo/OracleLinux/OL9/appstream/x86_64"
repo --name="ol9_UEKR7" --baseurl="https://yum.oracle.com/repo/OracleLinux/OL9/UEKR7/x86_64"
repo --name="ol9_BaseOS" --baseurl="https://yum.oracle.com/repo/OracleLinux/OL9/baseos/latest/x86_64"
repo --name="ol9_EPEL" --baseurl="https://yum.oracle.com/repo/OracleLinux/OL9/developer/EPEL/x86_64" --install
repo --name="ol9_addons" --baseurl="https://yum.oracle.com/repo/OracleLinux/OL9/addons/x86_64"
#repo --name="docker-ce" --baseurl="https://download.docker.com/linux/centos/9/x86_64/stable" --install
repo --name=openvswitch --baseurl="https://mirror.stream.centos.org/SIGs/9-stream/nfv/x86_64/openvswitch-2/" --install

url --url="https://yum.oracle.com/repo/OracleLinux/OL9/baseos/latest/x86_64"

%packages
linux-firmware
microcode_ctl
at
audispd-plugins
audit
bridge-utils
ca-certificates
chrony
curl
pcp-system-tools
gnupg
hddtemp
irqbalance
jq
lbzip2
linuxptp
net-tools
openssh-server
edk2-ovmf
podman
python3-dnf
python3-cffi
python3-setuptools
python3.11
python3.11-lxml
python3.11-pip
net-snmp
net-snmp-utils
sudo
sysfsutils
syslog-ng
sysstat
vim
wget
rsync
pciutils
conntrack-tools

busybox
python-gunicorn
ipmitool
nginx
ntfs-3g
python3-flask-wtf
python3-pip
corosync
pacemaker
openvswitch3.4

#kernel-rt
grubby
#kernel-rt-kvm
qemu-kvm

#ceph
#ceph-base
#ceph-common
#ceph-mgr
#ceph-mgr-diskprediction-local
#ceph-mon
#ceph-osd
#libcephfs2
libvirt
libvirt-daemon
libvirt-daemon-driver-storage-rbd
#python3-ceph-argparse
#python3-cephfs
#tuna

#tuned
#tuned-profiles-nfv
#tuned-profiles-realtime

virt-install

pcs
pcs-snmp

systemd-networkd
systemd-resolved

#for crmsh build
@development

#libvirt-clients
#lm-sensors

@virtualization-hypervisor

%end

# additional file changes
%post
cat <<EOF > /etc/motd
 ____  _____    _    ____   _  _____ _   _
/ ___|| ____|  / \  |  _ \ / \|_   _| | | |
\___ \|  _|   / _ \ | |_) / _ \ | | | |_| |
 ___) | |___ / ___ \|  __/ ___ \| | |  _  |
|____/|_____/_/   \_\_| /_/   \_\_| |_| |_|
EOF

rpm --import http://sumaproxy.rtsystem.com/pub/oracle-gpg-pubkey-BC4D06A08D8B756F.key
rpm --import https://www.centos.org/keys/RPM-GPG-KEY-CentOS-SIG-NFV

echo "EDITOR=vim" >> /etc/environment
echo "SYSTEMD_EDITOR=vim" >> /etc/environment
echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

echo "Defaults:ansible !requiretty" >> /etc/sudoers
echo "ansible    ALL=NOPASSWD:EXEC:SETENV: /bin/sh" >> /etc/sudoers
echo "ansible    ALL=NOPASSWD: /usr/bin/rsync" >> /etc/sudoers
echo "ansible    ALL=NOPASSWD: /usr/local/bin/crm" >> /etc/sudoers
echo "ansible    ALL=NOPASSWD: /usr/bin/ceph" >> /etc/sudoers

echo "virtu   ALL=NOPASSWD: ALL" >> /etc/sudoers

cat <<EOF > /etc/profile.d/custom-path.sh
PATH=$PATH:/usr/local/bin/
EOF

cat <<EOF > /etc/systemd/network/01-init.network
[Match]
Name=enp1s0
[Network]
Address=10.10.10.201/24
Gateway=10.10.10.1
EOF

echo "DNS=8.8.8.8" >> /etc/systemd/resolved.conf

pip-3.11 install packaging python-dateutil PyYAML
git clone https://github.com/ClusterLabs/crmsh.git /tmp/crmsh
cd /tmp/crmsh
./autogen.sh
PYTHON=/usr/bin/python3.11 ./configure
make
make install
ln -s /usr/local/bin/crm /usr/bin/crm
mkdir -p  /var/log/crmsh/

dnf -y remove @development

CEPH_RELEASE=19.2.1
curl -o /tmp/cephadm --silent --remote-name --location https://download.ceph.com/rpm-${CEPH_RELEASE}/el9/noarch/cephadm
chmod +x /tmp/cephadm
mv /tmp/cephadm /usr/local/bin/cephadm
/usr/local/bin/cephadm add-repo --release squid
/usr/local/bin/cephadm install ceph-common ceph-volume

grubby --set-default-index=0

%end
