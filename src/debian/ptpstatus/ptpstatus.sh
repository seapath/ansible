#!/bin/bash
# Copyright (C) 2024, Savoir-faire Linux, Inc
# SPDX-License-Identifier: Apache-2.0

die()
{
	local _ret="${2:-1}"
	test "${_PRINT_HELP:-no}" = yes && print_help >&2
	echo "$1" >&2
	exit "${_ret}"
}


# THE DEFAULTS INITIALIZATION - POSITIONALS
_positionals=()
# THE DEFAULTS INITIALIZATION - OPTIONALS
_arg_interval="1"


print_help()
{
	printf '%s\n' "The general script's help msg"
	printf 'Usage: %s [-i|--interval <secs>] [-h|--help] <stats> <details>\n' "$0"
	printf '\t%s\n' "<stats>: Stats file path"
	printf '\t%s\n' "<details>: Stats details file path"
	printf '\t%s\n' "-i, --interval: Time in sec between two status (default: '1')"
	printf '\t%s\n' "-h, --help: Prints help"
}


parse_commandline()
{
	_positionals_count=0
	while test $# -gt 0
	do
		_key="$1"
		case "$_key" in
			-i|--interval)
				test $# -lt 2 && die "Missing value for the optional argument '$_key'." 1
				_arg_interval="$2"
				shift
				;;
			--interval=*)
				_arg_interval="${_key##--interval=}"
				;;
			-i*)
				_arg_interval="${_key##-i}"
				;;
			-h|--help)
				print_help
				exit 0
				;;
			-h*)
				print_help
				exit 0
				;;
			*)
				_last_positional="$1"
				_positionals+=("$_last_positional")
				_positionals_count=$((_positionals_count + 1))
				;;
		esac
		shift
	done
}


handle_passed_args_count()
{
	local _required_args_string="'stats' and 'details'"
	test "${_positionals_count}" -ge 2 || _PRINT_HELP=yes die "FATAL ERROR: Not enough positional arguments - we require exactly 2 (namely: $_required_args_string), but got only ${_positionals_count}." 1
	test "${_positionals_count}" -le 2 || _PRINT_HELP=yes die "FATAL ERROR: There were spurious positional arguments --- we expect exactly 2 (namely: $_required_args_string), but got ${_positionals_count} (the last one was: '${_last_positional}')." 1
}

parse_commandline "$@"
handle_passed_args_count

STATS_FILE="${_positionals[0]}"
DETAILS_FILE="${_positionals[1]}"

echo "Interval is $_arg_interval"
echo "Stats file is $STATS_FILE"
echo "Details file is $DETAILS_FILE"

if [ ! -f /usr/sbin/pmc ] ; then
    echo "Error: pmc must be installed to continue" 1>&2
    exit 1
fi

StateDir=$(dirname $STATS_FILE 2>/dev/null)
mkdir -p $StateDir
if [ $? -ne 0 ] ; then
    echo "Error: Unable to create directory $StateDir" 1>&2
    exit 1
fi

DetailsDir=$(dirname $DETAILS_FILE 2>/dev/null)
mkdir -p $DetailsDir
if [ $? -ne 0 ] ; then
    echo "Error: Unable to create directory $DetailsDir" 1>&2
    exit 1
fi

echo 0 > "$STATS_FILE"

updateState()
{
    pmc_output=$(/usr/sbin/pmc -s /var/run/timemaster/ptp4l.0.socket -u -b 0 'GET PARENT_DATA_SET' 'GET TIME_STATUS_NP' 'GET PORT_DATA_SET')
    if [ $? -ne 0 ] ; then
        echo "Error: pmc failed" 1>&2
        echo 0 > "$STATS_FILE"
        return
    fi
    echo "$pmc_output" > "$DETAILS_FILE"
    if echo "$pmc_output" | grep gmPresent | grep -q true ; then
        gmp_present=1
    else
        gmp_present=0
    fi
    clock_class=$(echo "$pmc_output" | grep gm.ClockClass | grep -Eo '[0-9]+')
    if [ -z "$clock_class" ] ; then
        echo "Error: clockClass not found" 1>&2
        echo 0 > "$STATS_FILE"
        return
    fi
    # Check if Clock Classs is not out of the spec (not 52, 58, 187 and 193) and GMP is present
    if [[ $clock_class -ne 52 && $clock_class -ne 58 && $clock_class -ne 187 && $clock_class -ne 193 && $gmp_present -eq 1 ]] ; then
        echo 1 > "$STATS_FILE"
        return
    else
        echo 2 > "$STATS_FILE"
        return
    fi
}

while true ; do
    updateState
    sleep "$_arg_interval"
done
