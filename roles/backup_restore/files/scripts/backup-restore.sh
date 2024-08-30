#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

conffile=/etc/backup-restore.conf
# clean screen proportion
clear
for i in 50 100; do
   echo $i
   sleep 0.1
done | whiptail --gauge "Doing something" 10 50 0

function addExitToArray {
  local -n myarray=$1
  myarray+=("(exit)")
  myarray+=(" ")
}
function addIndexToArray {
  local -n myarray=$1
  for idx in `seq 1 ${#myarray[@]}`; do
    arrVar+=($idx")")
    arrVar+=("${myarray[$(($idx-1))]}")
  done
}
function getVars {
  source ${conffile}
  include_vm=${include_vm:-".*"}
  exclude_vm=${exclude_vm:-NonExistingGuestNameForDefault}
}
function getVarsOld {
  readVar local_dir
  local_dir=$value
  readVar remote_serv
  remote_serv=$value
  readVar remote_dir
  remote_dir=$value
  readVar local_tmp_dir
  local_tmp_dir=$value
  readVar remote_shell
  remote_shell=$value
}
function restoreVMChooseFullDate {
  while [ 1 ]
  do
    getVars
    [ -z "$local_tmp_dir" ] && { whiptail --msgbox "var local_tmp_dir empty" 10 50; break; }
    [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; break; }
    [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; break; }
    [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; break; }

    local listFullDate=($($remote_shell $remote_serv "cd $remote_dir ; ls"))
    local arrVar=()
    addIndexToArray listFullDate
    addExitToArray arrVar
    CHOICE=$(
    whiptail --title "restore vm" --cancel-button "back" --menu "Choose full backup date:" 22 115 14 \
          "${arrVar[@]}" \
          3>&2 2>&1 1>&3
    )
    [[ "$?" = 1 ]] && break
    [[ $CHOICE == "(exit)" ]] && exit
    c=`echo $CHOICE | sed "s/)//"`
    c=$((($c-1)*2+1))
    fulldate=${arrVar[$c]}
    restoreVMChooseVM
  done
}
function restoreVMChooseVM {
  while [ 1 ]
  do
    local listVM=($($remote_shell $remote_serv "cd $remote_dir ; cd $fulldate; ls *.qcow2 | grep -E "^system_" | cut -d"_" -f 2 | sort -u"))
    local arrVar=()
    addIndexToArray listVM
    addExitToArray arrVar
    CHOICE=$(
    whiptail --title "restore vm" --cancel-button "back" --menu "Choose VM:" 22 115 14 \
          "${arrVar[@]}" \
          3>&2 2>&1 1>&3
    )
    [[ "$?" = 1 ]] && break
    [[ $CHOICE == "(exit)" ]] && exit
    c=`echo $CHOICE | sed "s/)//"`
    c=$((($c-1)*2+1))
    vm=${arrVar[$c]}
    restoreVMChooseIncDate
  done
}
function restoreVMChooseIncDate {
  local listIncDateRaw=($($remote_shell $remote_serv "cd $remote_dir ; cd $fulldate; ls *_""$vm""-*.xml | cut -d- -f2 | cut -d. -f1"))
  local listIncDate=()
  for idx in ${listIncDateRaw[@]}; do
    e=`echo "$idx" | sed 's/./&-/4;s/./&-/7;s/./& /10;s/./&:/13'`
    listIncDate+=("$e")
  done
  local arrVar=()
  addIndexToArray listIncDate
  addExitToArray arrVar
  CHOICE=$(
  whiptail --title "restore vm" --cancel-button "back" --menu "Choose Incremental backup:" 22 115 14 \
        "${arrVar[@]}" \
        3>&2 2>&1 1>&3
  )
  [[ "$?" = 1 ]] && return
  [[ $CHOICE == "(exit)" ]] && exit
  c=`echo $CHOICE | sed "s/)//"`
  #d=$((($c-1)*2+1))
  #incdate=${arrVar[$d]}
  d=$(($c-1))
  incdate=${listIncDateRaw[$d]}
  /usr/local/bin/restore_vm.sh $local_tmp_dir "$remote_shell" $remote_serv:$remote_dir $fulldate $vm $incdate
}
function writeVar {
  key=$1
  value=$2
  valuesed=`echo $value | sed -e 's/\//\\\\\//g'`
  grep -q -E "^${key}=" ${conffile} && sed -i "s/^${key}=.*$/${key}=${valuesed}/" ${conffile} || echo "${key}=${value}" >> ${conffile}
  sort -u -t= -k1,1 ${conffile} -o ${conffile}
}
function readVar {
  key=$1
  value=`grep -E "^${key}=" ${conffile} | cut -d"=" -f2`
}
function backupFull {
  getVars
  [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; return; }
  [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; return; }
  [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; return; }
  /usr/local/bin/backup_full.sh $local_dir "$remote_shell" $remote_serv":"$remote_dir "$include_vm" "$exclude_vm"
}
function backupInc {
  getVars
  [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; return; }
  [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; return; }
  [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; return; }
  /usr/local/bin/backup_inc.sh $local_dir "$remote_shell" $remote_serv":"$remote_dir "$include_vm" "$exclude_vm"
}
function getValueForVar {
   var=$1
   val=$(whiptail --inputbox "Enter value for $var" 10 30 3>&1 1>&2 2>&3)
   [[ "$?" = 1 ]] && return
   writeVar $var $val
}
function settings {
  while [ 1 ]
  do
    touch ${conffile}
    source ${conffile}
    CHOICE=$(
    whiptail --title "change settings" --cancel-button "back" --menu "Make your choice" 22 115 14 \
          "1)" "change value local_dir, currently \"$local_dir\""   \
          "2)" "change value remote_serv, currently \"$remote_serv\""   \
          "3)" "change value remote_dir, currently \"$remote_dir\""   \
          "4)" "change value local_tmp_dir, currently \"$local_tmp_dir\""   \
          "5)" "change value remote_shell, currently \"$remote_shell\""   \
          "6)" "change value include_vm, currently \"$include_vm\""   \
          "7)" "change value exclude_vm, currently \"$exclude_vm\""   \
          3>&2 2>&1 1>&3
    )
    [[ "$?" = 1 ]] && break
    case $CHOICE in
      "1)") getValueForVar local_dir
      ;;
      "2)") getValueForVar remote_serv
      ;;
      "3)") getValueForVar remote_dir
      ;;
      "4)") getValueForVar local_tmp_dir
      ;;
      "5)") getValueForVar remote_shell
      ;;
      "6)") getValueForVar include_vm
      ;;
      "7)") getValueForVar exclude_vm
      ;;
    esac
  done
}

function estimate {
    getVars
    CMD="/usr/local/bin/backup_du.py \"${include_vm}\" \"${exclude_vm}\""
    echo "Estimating backup volume, please wait"
    echo
    whiptail --title "Estimated Volume for a FULL Backup" --msgbox "$(${CMD})" --scrolltext 15 78
}

while [ 1 ]
do
  CHOICE=$(
  whiptail --title "backup-restore" --cancel-button "exit" --menu "Make your choice" 22 100 14 \
    "1)" "backup full"   \
    "2)" "backup inc"   \
    "3)" "restore vm"   \
    "4)" "change settings"   \
    "5)" "estimate backup volume"   \
    3>&2 2>&1 1>&3
  )
  [[ "$?" = 1 ]] && break

  case $CHOICE in
    "1)") backupFull
    ;;
    "2)") backupInc
    ;;
    "3)") restoreVMChooseFullDate
    ;;
    "4)") settings
    ;;
    "5)") estimate
    ;;
  esac
done
