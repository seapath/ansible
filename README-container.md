# Docker Compose Pacemaker Resource Agent for SEAPATH

## Requirements

- [`wetopi/rbd` plugin](https://github.com/wetopi/docker-volume-rbd/) for Ceph-backed persistent storage.
- `docker-compose` (the legacy Python-based tool, **not** the newer `docker compose` plugin).
- yq https://github.com/mikefarah/yq/releases/tag/v4.47.2

## SPECIFICATIONS OF THE DOCKER COMPOSE FILE

This resource agent (RA) works with standard `docker-compose.yml` files. If your containers require persistent storage using Ceph, you must specify the `wetopi/rbd` driver for your Docker volumes. This plugin manages volume creation with RBD, enabling containers to access data from any node in the Ceph cluster.

**Example:**

```yaml
volumes:
    influxdb_data:
        driver: wetopi/rbd:latest
        driver_opts:
            size: 10240
            fstype: ext4
```

- `size`: Size of the RBD volume in megabytes.
- `fstype`: Filesystem type to format the volume (e.g., `ext4`).

For more configuration options and details, refer to the [wetopi/docker-volume-rbd documentation](https://github.com/wetopi/docker-volume-rbd/).

## DEPLOY THE DOCKER COMPOSE RESOURCE AGENT

To deploy the docker-compose resource agent, we need to use role copy_ra_docker_compose with ansible by specifying the deploy_docker_compose playbook and inventory the seapath-cluster.yml inventory used to deploy seapath


## CREATING A RESOURCE WITH THE docker-compose RA

1. **Create a directory** for your resource under `/opt` (replace `my_resource_name` with your desired name):

    ```sh
    sudo mkdir /opt/my_resource_name
    ```

2. **Copy your `docker-compose.yml` file** into this directory:

    ```sh
    sudo cp path/to/your/docker-compose.yml /opt/my_resource_name/
    ```

3. **Register the resource with Pacemaker** using the following command (update `my_resource_name` as needed):

    ```sh
    crm configure primitive my_resource_name ocf:seapath:docker-compose \
         params name="my_resource_name" ymlfile="docker-compose.yml" \
         op monitor interval=30s timeout=20s on-fail=restart \
         op start timeout=280s \
         op stop timeout=360s
    ```

    - Adjust the `timeout` values for `start`, `stop`, `monitor`, and `restart` as appropriate for your environment.

This will create and manage your Docker Compose resource with Pacemaker using the specified configuration.

## Floating IP Address

To make your resource accessible via the same IP address regardless of which cluster node is active, configure a floating IP using Pacemaker:

1. **Create an IPAddr2 resource** with your desired IP address and network interface:

    ```sh
    crm configure primitive my_resource_ip ocf:heartbeat:IPaddr2 \
        params ip="YOUR_FLOATING_IP" cidr_netmask="YOUR_NETMASK" nic="YOUR_INTERFACE" \
        op monitor interval=10s
    ```

    - Replace `YOUR_FLOATING_IP` with the IP address you want to assign.
    - Replace `YOUR_NETMASK` with the appropriate CIDR netmask (e.g., `24`).
    - Replace `YOUR_INTERFACE` with the network interface (e.g., `eth0` or `br0`).

2. **Set colocation and ordering constraints** so the floating IP and your Docker Compose resource always move together:

    ```sh
    crm configure colocation my_resource_vip inf: my_resource my_resource_ip
    crm configure order my_resource_order Mandatory: my_resource_ip my_resource
    ```

This ensures the floating IP always follows your Docker Compose resource, providing consistent access to your service no matter which node is running it.

## Limitations

Tests for performance have not been conducted yet, and the code has not been tested in a production environment.