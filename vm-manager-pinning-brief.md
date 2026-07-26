# Brief — Intégration du pinning profile dans vm_manager

## Contexte

SEAPATH dispose d'un système d'allocation dynamique des cœurs CPU pour les VMs
KVM. Le profil de pinning de chaque VM est stocké en métadonnées Ceph RBD, sous
la clé `seapath.pinning.v1` (valeur : YAML). Ce profil est lu au démarrage de la
VM par un hook libvirt déployé sur les nœuds SEAPATH.

Aujourd'hui, le profil est écrit à la main :
```bash
rbd image-meta set <pool>/system_<vmname> seapath.pinning.v1 '<yaml>'
```

L'objectif de ce brief est d'intégrer cette écriture dans `vm_manager` — le
gestionnaire de VMs Python de SEAPATH — pour qu'elle soit faite automatiquement
lors du déploiement d'une VM.

## Dépôt cible

`seapath/vm_manager` — **pas** `seapath-ansible`.

Les modifications sont ensuite propagées dans seapath-ansible via le submodule
`roles/deploy_vm_manager/files/vm_manager/`.

## Architecture vm_manager (rappel)

`vm_manager` gère les VMs en mode cluster via `vm_manager_cluster.py`.
La fonction centrale est `_configure_vm(vm_name, vm_options, ...)`, appelée par
`create()` et `clone()`. C'est là que toutes les métadonnées sont écrites sur
l'image système (`system_<vmname>`) via le helper `RbdManager` :

```python
with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
    rbd.set_image_metadata(disk_name, "some.key", "some_value")
```

`rbd_manager.py` (`helpers/rbd_manager.py`) expose `set_image_metadata(image, key, value)`
et `get_image_metadata(image, key)`. Ces méthodes acceptent n'importe quel nom de clé
avec des points — **pas de contrainte** à ce niveau.

## Point de friction — `_check_name()`

`_check_name(name)` valide les noms passés par l'utilisateur et n'accepte que
`[a-zA-Z0-9]`. Elle est appelée dans `create()`, `clone()`, `set_metadata()`, etc.

La clé `seapath.pinning.v1` contient des points → elle serait rejetée si on la
faisait passer par `_check_name`. La solution est de **ne pas** l'y faire passer :
c'est une clé interne connue, pas un nom arbitraire fourni par l'utilisateur.
Le pattern est identique à `_live_migration`, `_preferred_host` et autres
paramètres internes qui contournent `_check_name`.

## Modifications à apporter

### 1. `vm_manager_cluster.py` — `_configure_vm()`

Ajouter un bloc pour le profil de pinning, après les autres blocs de métadonnées
existants :

```python
if "pinning_profile" in vm_options:
    rbd.set_image_metadata(
        disk_name, "seapath.pinning.v1", vm_options["pinning_profile"]
    )
```

`pinning_profile` est une string YAML (contenu du fichier profil, pas un chemin).
La conversion fichier → string se fait dans la CLI (voir §4).

### 2. `vm_manager_cluster.py` — `create()`

Accepter `pinning_profile` comme paramètre optionnel et le transmettre à
`_configure_vm()` :

```python
def create(vm_name, ..., pinning_profile=None):
    vm_options = {...}
    if pinning_profile is not None:
        vm_options["pinning_profile"] = pinning_profile
    _configure_vm(vm_name, vm_options, ...)
```

### 3. `vm_manager_cluster.py` — `clone()`

Copier le profil depuis l'image source vers la destination. Si un profil est
explicitement fourni, il prend le dessus :

```python
def clone(src_name, dst_name, ..., pinning_profile=None):
    ...
    with RbdManager(...) as rbd:
        if pinning_profile is None:
            try:
                pinning_profile = rbd.get_image_metadata(
                    OS_DISK_PREFIX + src_name, "seapath.pinning.v1"
                )
            except Exception:
                pass  # source has no profile — that's fine
    vm_options = {...}
    if pinning_profile is not None:
        vm_options["pinning_profile"] = pinning_profile
    _configure_vm(dst_name, vm_options, ...)
```

### 4. `vm_manager_cluster.py` — nouvelle fonction `set_pinning_profile()`

Pour mettre à jour le profil d'une VM déjà déployée sans passer par
`set_metadata()` (qui appellerait `_check_name`) :

```python
def set_pinning_profile(vm_name, yaml_str):
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        rbd.set_image_metadata(disk_name, "seapath.pinning.v1", yaml_str)
```

Et la fonction miroir :

```python
def get_pinning_profile(vm_name):
    with RbdManager(CEPH_CONF, POOL_NAME, NAMESPACE) as rbd:
        disk_name = OS_DISK_PREFIX + vm_name
        return rbd.get_image_metadata(disk_name, "seapath.pinning.v1")
```

### 5. `vm_manager_cmd.py` — modifications CLI

#### `create` subcommand
Ajouter `--pinning-profile <fichier.yaml>` :
```python
create_parser.add_argument(
    "--pinning-profile", metavar="FILE",
    help="YAML pinning profile to store in RBD image metadata"
)
```
Dans le handler, lire le fichier et passer le contenu à `create()` :
```python
pinning_profile = None
if args.pinning_profile:
    with open(args.pinning_profile) as f:
        pinning_profile = f.read()
create(args.vm_name, ..., pinning_profile=pinning_profile)
```

#### `clone` subcommand
Même chose avec `--pinning-profile` optionnel. Sans l'option, le profil de la
source est copié automatiquement (voir §3).

#### Nouveau subcommand `set-pinning-profile`
```
vm-mgr set-pinning-profile <vm_name> <fichier.yaml>
```
Lit le fichier et appelle `set_pinning_profile(vm_name, yaml_str)`.

#### Nouveau subcommand `get-pinning-profile`
```
vm-mgr get-pinning-profile <vm_name>
```
Appelle `get_pinning_profile(vm_name)` et affiche le YAML.

## Schéma du profil YAML

```yaml
version: 1
vcpus:
  isolation: exclusive_physical   # none | shared_rt | exclusive_logical | exclusive_physical
  scheduler: FIFO                 # FIFO | RR | OTHER | BATCH
  priority: 90
emulator:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
vhost:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
iothread:
  isolation: none
  scheduler: OTHER
  priority: 0
```

Toutes les clés sont optionnelles — le hook libvirt complète les valeurs
manquantes depuis ses propres defaults.

## Comment tester

```bash
# Créer une VM avec un profil
vm-mgr create myvm --image myvm.qcow2 --pinning-profile rt-profile.yaml

# Vérifier que la métadonnée est bien écrite
rbd image-meta get rbd/system_myvm seapath.pinning.v1

# Mettre à jour le profil d'une VM existante
vm-mgr set-pinning-profile myvm new-profile.yaml
rbd image-meta get rbd/system_myvm seapath.pinning.v1  # doit afficher le nouveau profil

# Cloner : le profil est copié automatiquement
vm-mgr clone myvm myclone
rbd image-meta get rbd/system_myclone seapath.pinning.v1  # même profil que myvm

# Cloner avec override
vm-mgr clone myvm myclone2 --pinning-profile other-profile.yaml
rbd image-meta get rbd/system_myclone2 seapath.pinning.v1  # doit afficher other-profile
```

**Critère de réussite :** après `vm-mgr create myvm --pinning-profile rt.yaml`,
démarrer la VM avec `virsh start myvm` — le hook libvirt lit le profil depuis les
métadonnées RBD et applique le pinning sans aucune commande manuelle.

## Conventions du dépôt

- Python 3.8+, ligne max 79 caractères
- Formatage : Black (`black -l 79 -t py38`)
- Linting : flake8, pylint
- Licence : Apache-2.0, toutes les sources ont un header copyright RTE
- Validation des noms utilisateur via `_check_name()` — ne pas l'appliquer aux
  clés internes (`seapath.pinning.v1` en particulier)
