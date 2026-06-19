#!/bin/bash
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

set -e

print_usage()
{
    echo "This script generates a latency graph based on cyclictest output
    For instance:
        $ cyclictest -l100000000 -m -Sp90 -i200 -h400 -q >output
        $ $0 -i output -n 28 -o seapath.png -l 100

./$(basename "${0}") [OPTIONS]

Options:
        (-i|--input)            <path>          Input file to process
        (-o|--output)           <path>          Output file to process
        (-l|--limit)            <latency>       Latency value for limit line
        (-h|--help)                             Display this help message
        "
}

# Name:       parse_options
# Brief:      Parse options from command line
# Param[in]:  Command line parameters
parse_options()
{
    ARGS=$(getopt -o "hi:o:l:" -l "input:,output:,limit:" -n "$0" -- "$@")

    eval set -- "${ARGS}"

    while true; do
        case "$1" in
            -i|--input)
                export INPUT_FILE=$2
                shift 2
                ;;

            -o|--output)
                export OUTPUT_FILE=$2
                shift 2
                ;;

            -l|--limit)
                export LIMIT=$2
                shift 2
                ;;

            -h|--help)
                print_usage
                exit 1
                ;;

            -|--)
                shift
                break
                ;;

            *)
                print_usage
                exit 1
                ;;
        esac
    done
}

# The 3 following functions are fetched from
# https://www.osadl.org/Create-a-latency-plot-from-cyclictest-hi.bash-script-for-latency-plot.0.html

# Name:       plot_graph
# Brief:      Plot a graph based on a plot file
# Param[in]:  Maximum latency to plot
# Param[in]:  Core count
# Param[in]:  Plot file to use
# Param[in]:  Output image file
plot_graph()
{
    local max_latency=$1
    local cores=$2
    local plot_file=$3
    local output_file=$4
    local histogram_file=$5

    # default value
    if [ -z "$LIMIT" ]; then
      echo Missing LIMIT
      exit 1
    fi

    # Create plot command header
    echo -n -e "set title \"Latency plot\"\n\
    set xlabel \"Latency (µs)\"\n\
    set terminal pngcairo \n\
    set logscale y\n\
    set xrange [0:400]\n\
    set yrange [0.8:*]\n\
    set ylabel \"Number of latency samples\"\n\
    set arrow from $LIMIT, graph 0 to $LIMIT, graph 1 nohead dt 2 lw 3 lc rgb 'red'

    set output \"$output_file\"\n\
    plot " >"$plot_file"


    # Append plot command data references
    for i in $(seq 1 "$cores"); do
        if [[ "$i" != 1 ]]; then
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

    gnuplot -persist <"$plot_file"
}

# Name:       create_histogram
# Brief:      Create Histogram file
# Param[in]:  Input file
create_histogram()
{
    local input_file=$1
    local histogram_file=$2
    # Grep data lines, remove empty lines and create a common field separator
    grep -v -e "^#" -e "^$" "$input_file" | tr " " "\t" >"$histogram_file"
}

# Name:       create_histogram_per_core
# Brief:      Create Histogram file per core
# Param[in]:  Core count
# Param[in]:  Histogram file
create_histogram_per_core()
{
    local cores=$1
    local histogram_file=$2
    # Create two-column data sets with latency classes and frequency values for each core, for example
    for i in $(seq 1 "$cores")
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
    grep "Max Latencies" "$input_file" | tr " " "\n" | sort -n | tail -1 | sed s/^0*//
}

# Name:       get_core_count
# Param[in]:  Input file
get_core_count()
{
    local input_file=$1
    grep -c "# Thread " "$input_file"
}

##########################
########## MAIN ##########
##########################

# Not verbose by default
export VERBOSE=0

# Parse options
parse_options "${@}"

# Keep directory to retrieve tools
TEMP_DIR=$(mktemp -d)
HISTOGRAM_FILE=$TEMP_DIR/histogram
PLOT_FILE=$TEMP_DIR/plotcmd

max_latency=$(get_max_latency "$INPUT_FILE")
cpus=$(get_core_count "$INPUT_FILE")
create_histogram "$INPUT_FILE" "$HISTOGRAM_FILE"
create_histogram_per_core "$cpus" "$HISTOGRAM_FILE"
plot_graph "$max_latency" "$cpus" "$PLOT_FILE" "$OUTPUT_FILE" "$HISTOGRAM_FILE"

rm -rf "$TEMP_DIR"
