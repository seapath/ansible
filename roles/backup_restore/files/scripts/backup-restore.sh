#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

conffile=/etc/backup-restore.conf

# Display a whiptail menu over the given items and print the (0-based) index
# of the selected one. Returns 1 if the user chose "back", 2 for "(exit)".
function menuChooseIndex {
  local title=$1 prompt=$2
  shift 2
  local items=("$@")
  local args=() idx choice
  for idx in "${!items[@]}"; do
    args+=("$((idx + 1)))" "${items[$idx]}")
  done
  args+=("(exit)" " ")
  choice=$(whiptail --title "$title" --cancel-button "back" --menu "$prompt" 22 115 14 \
           "${args[@]}" 3>&2 2>&1 1>&3) || return 1
  [[ "$choice" == "(exit)" ]] && return 2
  echo "$((${choice%")"} - 1))"
}

function getVars {
  source "$conffile"
  include_vm=${include_vm:-".*"}
  exclude_vm=${exclude_vm:-NonExistingGuestNameForDefault}
}

function restoreVMChooseFullDate {
  while true
  do
    getVars
    [ -z "$local_tmp_dir" ] && { whiptail --msgbox "var local_tmp_dir empty" 10 50; break; }
    [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; break; }
    [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; break; }
    [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; break; }

    local listFullDate=($($remote_shell $remote_serv "cd $remote_dir ; ls"))
    local idx
    idx=$(menuChooseIndex "restore vm" "Choose full backup date:" "${listFullDate[@]}")
    case $? in 1) break ;; 2) exit ;; esac
    fulldate=${listFullDate[$idx]}
    restoreVMChooseVM
  done
}

function restoreVMChooseVM {
  while true
  do
    local listVM=($($remote_shell $remote_serv "cd $remote_dir ; cd $fulldate; ls *.qcow2 | grep -E "^system_" | cut -d"_" -f 2 | sort -u"))
    local idx
    idx=$(menuChooseIndex "restore vm" "Choose VM:" "${listVM[@]}")
    case $? in 1) break ;; 2) exit ;; esac
    vm=${listVM[$idx]}
    restoreVMChooseIncDate
  done
}

function restoreVMChooseIncDate {
  local listIncDateRaw=($($remote_shell $remote_serv "cd $remote_dir ; cd $fulldate; ls *_""$vm""-*.xml | cut -d- -f2 | cut -d. -f1"))
  local listIncDate=() rawdate
  for rawdate in "${listIncDateRaw[@]}"; do
    listIncDate+=("$(echo "$rawdate" | sed 's/./&-/4;s/./&-/7;s/./& /10;s/./&:/13')")
  done
  local idx
  idx=$(menuChooseIndex "restore vm" "Choose Incremental backup:" "${listIncDate[@]}")
  case $? in 1) return ;; 2) exit ;; esac
  incdate=${listIncDateRaw[$idx]}
  /usr/local/bin/restore_vm.sh "$local_tmp_dir" "$remote_shell" "$remote_serv:$remote_dir" "$fulldate" "$vm" "$incdate"
}

function writeVar {
  local key=$1 value=$2
  local valuesed=$(echo "$value" | sed -e 's/\//\\\//g')
  grep -q -E "^${key}=" "$conffile" && sed -i "s/^${key}=.*$/${key}=${valuesed}/" "$conffile" || echo "${key}=${value}" >> "$conffile"
  sort -u -t= -k1,1 "$conffile" -o "$conffile"
}

function backupFull {
  getVars
  [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; return; }
  [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; return; }
  [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; return; }
  /usr/local/bin/backup_full.sh "$local_dir" "$remote_shell" "$remote_serv:$remote_dir" "$include_vm" "$exclude_vm"
}

function backupInc {
  getVars
  [ -z "$remote_dir" ] && { whiptail --msgbox "var remote_dir empty" 10 50; return; }
  [ -z "$remote_shell" ] && { whiptail --msgbox "var remote_shell empty" 10 50; return; }
  [ -z "$remote_serv" ] && { whiptail --msgbox "var remote_serv empty" 10 50; return; }
  /usr/local/bin/backup_inc.sh "$local_dir" "$remote_shell" "$remote_serv:$remote_dir" "$include_vm" "$exclude_vm"
}

function getValueForVar {
  local var=$1 val
  val=$(whiptail --inputbox "Enter value for $var" 10 30 3>&1 1>&2 2>&3) || return
  writeVar "$var" "$val"
}

function settings {
  local vars=(local_dir remote_serv remote_dir local_tmp_dir remote_shell include_vm exclude_vm)
  while true
  do
    touch "$conffile"
    source "$conffile"
    local items=() v idx
    for v in "${vars[@]}"; do
      items+=("change value $v, currently \"${!v}\"")
    done
    idx=$(menuChooseIndex "change settings" "Make your choice" "${items[@]}")
    case $? in 1) break ;; 2) exit ;; esac
    getValueForVar "${vars[$idx]}"
  done
}

function estimate {
  getVars
  echo "Estimating backup volume, please wait"
  whiptail --title "Estimated Volume for a FULL Backup" \
    --msgbox "$(/usr/local/bin/backup_du.py "$include_vm" "$exclude_vm")" --scrolltext 15 78
}

while true
do
  CHOICE=$(
  whiptail --title "backup-restore" --cancel-button "exit" --menu "Make your choice" 22 100 14 \
    "1)" "backup full"   \
    "2)" "backup inc"   \
    "3)" "restore vm"   \
    "4)" "change settings"   \
    "5)" "estimate backup volume"   \
    3>&2 2>&1 1>&3
  ) || break

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
