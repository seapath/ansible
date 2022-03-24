#!/bin/bash

vm=$1
if [ -z $vm ]
then
  echo no vm defined
else
  echo "you want a console to $vm, ok let's go"
  hyp=`crm status | grep -E "^  \* $vm" | grep Started | awk 'NF>1{print $NF}'`
  if [ -z $hyp ]
  then
    echo no hypervisor found for this vm
  else
    echo "$vm is running on $hyp, let's connect !"
    virsh --connect qemu+ssh://root@$hyp/system console $vm
  fi
fi
