#!/bin/bash
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

set -e

print_usage()
{
    echo "This script generates a latency graph based on cyclictest output
	For instance:
		$ cyclictest -l100000000 -m -Sp90 -i200 -h400 -q >output
		$ $0 -i output  -n 28 -o seapath.png

./$(basename "${0}") [OPTIONS]

Options:
        (-i|--input)			<path>			Input file to process
        (-n|--number)			<core>			Number of core
        (-o|--output)			<path>			Output file to process
        (-h|--help)                             		Display this help message
        "
}

# Name:       parse_options
# Brief:      Parse options from command line
# Param[in]:  Command line parameters
parse_options()
{
    ARGS=$(getopt -o "hi:n:o:" -l "input:,number:,output:" -n "$0" -- "$@")

    eval set -- "${ARGS}"

    while true; do
        case "$1" in
            -i|--input)
                export INPUT_FILE=$2
                shift 2
                ;;

            -n|--number)
                export NB_CORES=$2
                shift 2
                ;;

            -o|--output)
                export OUTPUT_FILE=$2
                shift 2
                ;;

            -h|--help)
                print_usage
                exit 1
                shift
                break
                ;;

            -|--)
                shift
                break
                ;;

            *)
                print_usage
                exit 1
                shift
                break
                ;;
        esac
    done
}

# Name:       plot_graph
# Brief:      Plot a graph based on a plot file
# Param[in]:  Maximum latency to plot
# Param[in]:  Plot file to use
# Param[in]:  Output image file
plot_graph()
{
    local max_latency=$1
    local plot_file=$2
    local output_file=$3
    local histogram_file=$4

    # Create plot command header
    echo -n -e "set title \"Latency plot\"\n\
    set terminal png\n\
    set xlabel \"Latency (us), max $max_latency us\"\n\
    set logscale y\n\
    set xrange [0:400]\n\
    set yrange [0.8:*]\n\
    set ylabel \"Number of latency samples\"\n\
    set output \"$output_file\"\n\
    plot " >"$plot_file"

    # Append plot command data references
    for i in `seq 1 $NB_CORES`; do
        if test $i != 1; then
            echo -n ", " >>"$plot_file"
        fi
        cpuno=$((i-1))
        if test $cpuno -lt 10; then
            title=" CPU$cpuno"
        else
            title="CPU$cpuno"
        fi
        echo -n "\"$histogram_file$i\" using 1:2 title \"$title\" with histeps" >>"$plot_file"
    done
    gnuplot -persist <$plot_file
}

# Name:       create_histogram
# Brief:      Create Histrogram file
# Param[in]:  Input file
create_histogram()
{
    local input_file=$1
    local histogram_file=$2
    # Grep data lines, remove empty lines and create a common field separator
    grep -v -e "^#" -e "^$" "$input_file" | tr " " "\t" >"$histogram_file"
}

# Name:       create_histogram_per_core
# Brief:      Create Histrogram file per core
# Param[in]:  Input file
# Param[in]:  Histogram file
create_histogram_per_core()
{
    local histogram_file=$1
    # Create two-column data sets with latency classes and frequency values for each core, for example
    for i in `seq 1 $NB_CORES`
    do
        column=$((i + 1))
        cut -f1,"$column" "$histogram_file" >"$histogram_file$i"
    done
}

# Name:       get_max_latency
# Brief:      Get the maximum latency
# Param[in]:  Input file
get_max_latency()
{
    local input_file=$1
    echo $(grep "Max Latencies" "$input_file" | tr " " "\n" | sort -n | tail -1 | sed s/^0*//)
}

##########################
########## MAIN ##########
##########################

#### Local vars ####
# Change to top directory
cd ${0%/*}

# Keep directory to retrieve tools
TOPDIR=${PWD}
TEMP_DIR=$(mktemp -d)
HISTOGRAM_FILE=$TEMP_DIR/histogram
PLOT_FILE=$TEMP_DIR/plotcmd

# Not verbose by default
export VERBOSE=0

# Parse options
parse_options "${@}"

max_latency=$(get_max_latency $INPUT_FILE)
create_histogram $INPUT_FILE $HISTOGRAM_FILE
create_histogram_per_core $HISTOGRAM_FILE
plot_graph $max_latency $PLOT_FILE $OUTPUT_FILE $HISTOGRAM_FILE
echo "Max Latency found=$max_latency us"
