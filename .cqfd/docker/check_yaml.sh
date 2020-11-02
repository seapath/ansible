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


directory="."
warms="--no-warnings"

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
        warms=""
        ;;
    --)
        shift
        break
        ;;
    esac
    shift
done

for yaml in $(find ${directory} -type f -regex '.*\(yml\|yaml\)$') ; do
    echo -n "test $yaml: "
    yamllint -f parsable "${warms}" "$yaml"
    echo "ok"
done
