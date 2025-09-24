install_yq
=========

yq is used while fixing a docker-compose limitation with the plugin wetopi/rbd. it allows to extract  volumes and they options into docker-compose.yml file and then create them  before creating containers


Example Playbook
----------------

- hosts: cluster_machines
  gather_facts: false
  roles:
    - role: install_yq

License
-------

BSD

Author Information
------------------

An optional section for the role authors to include contact information, or a website (HTML is not allowed).
