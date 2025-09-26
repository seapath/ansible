# copy_ra_docker_compose

This Ansible role deploys a Docker Compose file along with the `wetopi/rbd` plugin to simplify container deployment on Seapath.

## Prerequisites

- Ansible 2.9+
- Root or sudo access on target hosts
- Docker , Docker-Compose(or docker compose) or podman-compose installed on the hosts

## Variables

No required variables by default. You can customize the compose file path or other parameters as needed.

## Example Usage

```yaml
- hosts: servers
  become: true
  roles:
    - role: containers/copy_ra_docker_compose
```

## License

BSD

## Author

K. Kouamé
