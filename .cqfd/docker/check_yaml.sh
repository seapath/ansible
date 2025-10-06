#!/bin/bash

usage()
{
    echo 'usage: check_yaml.sh [-h] [--directory directory] [--warnings]'
    echo
    echo "Check yaml syntaxe with yamllint of all files in the given directory"
    echo 'optional arguments:'
    echo ' -h, --help                  show this help message and exit'
    echo ' -d, --directory directory   the directory where to analyse. Default is .'
    echo ' --warnings                  include warnings'
}

find_yaml()
{
    find "${1}" -type f -regex '.*\(yml\|yaml\)$' | grep -v -E \
        "^${1}/(ceph-ansible|roles/corosync|collections)"
}

# Name        C
# Brief       Print colorized string
# arg1        color name (see below)
# arg2        string
C()
{
    local color="$1"; shift
    local text="$*"
    local nc='\033[0m'
    local c

    # Only colorize a few terminal types
    case "$TERM" in
    linux*|xterm*|screen|vt102) ;;
    *)
        echo "$@"
        return
        ;;
    esac

    case "$color" in
        gray)   c='\033[1;30m' ;;
        red)    c='\033[1;31m' ;;
        green)  c='\033[1;32m' ;;
        yellow) c='\033[1;33m' ;;
        blue)   c='\033[1;34m' ;;
        purple) c='\033[1;35m' ;;
        cyan)   c='\033[1;36m' ;;

        orange_bg) c='\033[48;2;255;165;0m'
    esac

    printf "${c}${text}${nc}"
}

directory="."
warns="--no-warnings"

options=$(getopt -o hd: --long directory:,help -- "$@")
[ $? -eq 0 ] || {
    echo "Incorrect options provided"
    exit 1
}

eval set -- "$options"
while true; do
    case "$1" in
    -h|--help)
        usage
        exit 0
        ;;
    -d|--directory)
        shift
        directory="$1"
        ;;
    --warnings)
        warns=""
        ;;
    --)
        shift
        break
        ;;
    esac
    shift
done

errors=0
for yaml in $(find_yaml "${directory}") ; do
    output=$(yamllint -f parsable "${warns}" "$yaml")
    if [ -z "$output" ]
    then
        echo "$yaml: $(C green OK)"
    else
        echo "$yaml: $(C red KO)"
        echo $(C red $output)
        if [ -n "$verbose" ] ; then
            echo $(C gray "$output")
        fi
        ((errors=errors+1))
    fi
done

if [ $errors -eq 0 ]
then
    exit 0
else
    echo "There are $errors errors"
    exit 1
fi
