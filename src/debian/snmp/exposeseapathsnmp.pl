#!/usr/bin/perl
use strict;
use SNMP::Extension::PassPersist;

my $extsnmp = SNMP::Extension::PassPersist->new(
    backend_collect => \&update_tree,
    refresh         => 300
);
$extsnmp->run;

sub update_tree {
    my ($self) = @_;
    my $file_path = "/tmp/snmpdata.txt";
    open(my $file, '<', $file_path) or die "Could not open file '$file_path' $!";
    while (my $line = <$file>) {
        # Split the line at the first ":" character
        my @parts = split(/:/, $line, 2);
        # Ensure that there is one ":" character in the line
        if (scalar @parts == 2) {
            my $oid = $parts[0];
            $oid =~ s/^\s+|\s+$//g;  # Trim whitespace
            $oid = ".2.25.1936023920.1635018752.0".$oid;
            my $value = $parts[1];
            $value =~ s/^\s+|\s+$//g;  # Trim whitespace

            $self->add_oid_entry($oid, "string", substr($value, 0, 4000));
        }
    }
    close($file);
}

