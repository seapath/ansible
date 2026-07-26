# Brief Hackathon — Allocation dynamique des cœurs CPU sur SEAPATH

## 1. Qu'est-ce que SEAPATH ?

SEAPATH (Secure Edge Automation Platform and Trusted Hypervisor) est une
plateforme open source (LF Energy) de virtualisation KVM/QEMU pour les postes
électriques THT/HT. Elle fait tourner des applications de protection du réseau
électrique conformes à la norme IEC 61850 — typiquement des relais de protection
numérique et des IED (Intelligent Electronic Devices) virtualisés.

### Ce qui rend SEAPATH différent d'une infrastructure cloud ordinaire

**Le temps-réel est critique.** Les applications IEC 61850 ont des contraintes de
latence exprimées en **microsecondes**. Un retard dans le déclenchement d'un
disjoncteur peut provoquer un incident réseau sur le réseau de transport d'électricité.
C'est pourquoi SEAPATH utilise un noyau Linux **PREEMPT_RT** — un patch qui rend
toutes les sections critiques du noyau préemptibles, permettant à un thread applicatif
d'interrompre n'importe quelle activité noyau, y compris les drivers.

**Les cœurs sont isolés.** Au démarrage, le paramètre noyau `isolcpus=<liste>` retire
certains cœurs logiques de la file d'attente du scheduler Linux. Ces cœurs
**isolés** ne reçoivent aucune tâche du système ; ils sont réservés exclusivement
aux threads temps-réel des VMs, containers, et IRQs NIC. Les cœurs non-isolés
(appelés **housekeeping**) gèrent tout le reste : le système d'exploitation, les
daemons, etc.

**L'Hyper-Threading complique les choses.** Sur un processeur Intel avec
Hyper-Threading, chaque cœur physique présente **deux cœurs logiques** (appelés
siblings). Ces deux siblings partagent les ressources d'exécution du cœur physique
(cache L1, unités de calcul, TLB). Si on place deux threads RT indépendants sur les
deux siblings d'un même cœur physique, ils se perturbent mutuellement. Pour une
isolation maximale, on veut parfois réserver le cœur physique entier à un seul
thread — ce qui implique de laisser l'un des deux siblings complètement inactif.

**Exemple de topologie réelle :**
```
Cœurs housekeeping : 0, 1, 2, 3
Cœurs isolés       : 4, 5, 6, 7, 8, 9, 10, 11
Paires HT isolées  : (4,5), (6,7), (8,9), (10,11)
```

### Les acteurs qui s'exécutent sur les cœurs isolés

Sur un nœud SEAPATH, plusieurs types d'entités se partagent le pool de cœurs
isolés :

1. **Les VMs** (QEMU/KVM, gérées par libvirt) — déployées via Ansible
2. **Les containers** (Podman, orchestrés par systemd/quadlet) — déployés via Ansible
3. **Les IRQs des cartes réseau** — les NIC hautes performances génèrent des
   interruptions matérielles qui sont également épinglées à des cœurs isolés pour
   minimiser la latence réseau
4. **Les outils opérateurs** — un ingénieur peut lancer ponctuellement un générateur
   de trames Sampled Values (SV) ou un sniffer pour un test ou une recette ; ces
   outils ont aussi besoin de cœurs et de priorités RT

---

## 2. Comment les choses sont gérées aujourd'hui (et pourquoi ça pose problème)

### 2.1 Les VMs : pinning statique dans le XML libvirt

Aujourd'hui, l'affinité CPU des VMs est définie **à la création** dans la
définition XML libvirt, via le bloc `<cputune>` :

```xml
<cputune>
  <vcpupin vcpu="0" cpuset="4"/>
  <vcpupin vcpu="1" cpuset="6"/>
  <vcpusched vcpus="0" scheduler="fifo" priority="90"/>
  <vcpusched vcpus="1" scheduler="fifo" priority="90"/>
  <emulatorpin cpuset="8"/>
</cputune>
```

Ce XML est généré par Ansible depuis l'inventaire :

```yaml
cpuset: [4, 6]        # cœurs des vCPUs
emulatorpin: 8        # cœur du thread émulateur QEMU
rt_priority: 90       # priorité FIFO
```

**Problème 1 — Incompatibilité avec la migration à chaud.** Sur un cluster SEAPATH
(3 nœuds en général), une VM doit pouvoir migrer d'un nœud à l'autre. Si le XML
impose les cœurs 4 et 6, ces cœurs doivent être réservés *sur chaque nœud* où la
VM pourrait atterrir. Deux VMs migrables qui veulent toutes deux les cœurs 4 et 6
entrent en conflit dès qu'elles se retrouvent sur le même nœud.

**Problème 2 — La décision est prise au déploiement, pas au lancement.** Le bon
moment pour décider quels cœurs attribuer à une VM, c'est quand elle démarre — car
c'est là qu'on connaît la topologie exacte du nœud hôte et l'état réel d'occupation
des cœurs.

### 2.2 Les threads QEMU et leur comportement particulier

Un processus QEMU crée plusieurs threads aux rôles distincts, visibles dans
`/proc/<pid>/task/<tid>/comm` :

| Nom du thread (`comm`) | Rôle |
|---|---|
| `qemu-system-x86_64` (ou le nom de la VM) | Thread émulateur — boucle principale QEMU, I/O, migration |
| `CPU N/KVM` | Thread vCPU N — exécute le code guest en mode KVM |
| `vhost-N` | Thread kernel vhost — traitement des paquets virtio côté noyau |
| `iothreadN` | Thread I/O optionnel — offload disque/réseau |

**Point critique sur les threads vhost :** les threads `vhost-*` sont des threads
**noyau** créés par le kernel (pas par QEMU directement) en réponse à l'activation
d'une queue virtio par le guest. À leur création, ils héritent de l'affinité CPU du
thread qui les a déclenchés — typiquement le thread émulateur. Si on épingle
l'émulateur **après** que les threads vhost ont été créés avec une affinité par
défaut (tous les cœurs), les vhost ont déjà leur affinité définie et il faudra les
ré-épingler explicitement. L'ordre d'application doit être :
**vCPUs → émulateur → vhost → iothreads**.

### 2.3 Les containers : pinning statique dans l'unité systemd

Les containers Podman sur SEAPATH sont orchestrés via des fichiers **quadlet**
(une fonctionnalité systemd permettant de déclarer des containers comme des unités
`.container`). L'affinité CPU et la politique d'ordonnancement sont définies dans
la section `[Service]` de l'unité :

```ini
[Service]
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=4
CPUAffinity=0 1
```

**Même problème que pour les VMs :** la décision est prise au déploiement (dans le
fichier d'unité), pas au lancement. Si deux containers veulent le cœur 0, il y a
conflit. Si on déploie sur un nœud avec une topologie différente, les cœurs codés
en dur sont peut-être déjà pris.

### 2.4 Les IRQs NIC : pinning statique via un rôle dédié

Le rôle `configure_nic_irq_affinity` gère l'affinité des IRQs NIC de façon
entièrement statique : une configuration par interface est définie dans l'inventaire
Ansible et appliquée au démarrage du nœud (et ré-appliquée sur chaque événement
link-up). Ces cœurs ne changent pas dynamiquement.

Le système d'allocation n'a donc pas à coordonner avec ce rôle. Il lui suffit de
**lire passivement** les affinités en place via `/proc/irq/` pour savoir quels cœurs
sont occupés par des IRQs NIC et les exclure de ses propres allocations.

### 2.5 Les outils opérateurs : aucune gestion

Un ingénieur qui lance un générateur de SV ou un sniffer pour un test n'a
aujourd'hui aucun moyen de savoir quels cœurs sont déjà pris ni comment enregistrer
son outil pour éviter les conflits. Il fait ça à la main avec `taskset` et `chrt`,
sans vue d'ensemble.

---

## 3. Le besoin : une allocation dynamique pour tous les acteurs

### 3.1 Principe général

L'idée est de remplacer toutes les décisions statiques (XML, fichiers d'unité) par
une **allocation dynamique au moment du lancement**, sur la base de l'état réel du
nœud à cet instant. Un acteur déclare son besoin ("il me faut un cœur isolé exclusif
en FIFO 90") et le système lui attribue ce qui est disponible.

### 3.2 Les niveaux d'isolation

Trois niveaux d'isolation sont définis, du moins au plus contraignant :

| Niveau | Description | Cas d'usage |
|---|---|---|
| `none` | Cœurs housekeeping, le scheduler Linux décide | Threads non-RT, émulateur d'une VM non-critique |
| `exclusive_logical` | Un cœur logique isolé dédié, aucun autre thread n'y est épinglé | vCPU d'une VM RT standard, container RT |
| `exclusive_physical` | Un cœur physique entier : thread épinglé au sibling inférieur, sibling supérieur laissé inactif | vCPU d'une VM de protection critique |

Quand le niveau demandé n'est pas satisfaisable (pool épuisé), l'allocateur doit
dégrader gracieusement plutôt qu'annuler le démarrage : `exclusive_physical` →
`exclusive_logical` (isolation RT préservée, bruit HT possible) → housekeeping (plus
d'isolation RT). Chaque dégradation doit être loguée et observable.

### 3.3 La source de configuration des VMs : métadonnées RBD

Pour les VMs, le profil de pinning est stocké en **métadonnées de l'image RBD**
(Ceph). Valeur : du YAML.

```bash
rbd image-meta set <pool>/<image> _seapath_alloc '
version: 1
vcpus:
  isolation: exclusive_physical
  scheduler: FIFO
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
'
```

La clé `vcpus` accepte aussi une liste indexée par numéro de vCPU (forme 2) pour
les VMs avec une workload mixte RT/non-RT. Tous les champs sont optionnels, avec
des defaults raisonnables (`none` / `OTHER` / `0`).

**Pourquoi RBD ?** Le profil voyage avec le disque. Quand la VM migre vers un autre
nœud, le nouvel hôte lit les mêmes métadonnées et re-alloue dynamiquement sur sa
propre topologie.

### 3.4 La mécanique d'allocation : pool vivant, pas de base de données

La question centrale est : comment savoir quels cœurs sont déjà pris ?

**Idée : redécouverte en direct depuis `/proc`.**

Au lieu de maintenir une base de données des allocations, on lit l'état du noyau
directement. Un thread est considéré comme occupant des cœurs isolés si et seulement
si son `Cpus_allowed_list` est un sous-ensemble des cœurs isolés — un thread non
épinglé a tous les cœurs dans son masque et n'est pas comptabilisé.

Les IRQs NIC sont lues passivement de la même façon depuis `/proc/irq/`, en filtrant
sur les IRQs appartenant effectivement à des NICs physiques (pour ignorer les IRQs
système que le kernel peut aussi placer sur des cœurs isolés).

**Pourquoi pas une base de données ?** Ce fichier peut se désynchroniser (crash de
la VM, hook interrompu, redémarrage du nœud). La redécouverte live est
auto-correctrice : quand la VM meurt, ses threads disparaissent de `/proc`, ses
cœurs redeviennent disponibles immédiatement, sans cleanup explicite.

### 3.5 La sérialisation : un sémaphore flock, pas un daemon

Plusieurs acteurs peuvent vouloir allouer des cœurs simultanément. Sans
sérialisation, deux acteurs pourraient voir les mêmes cœurs libres et les réclamer
tous les deux.

**Idée : `flock(LOCK_EX)` sur un fichier dans `/run/`.**

Le verrou est tenu pendant toute la fenêtre découverte → allocation → application
du pinning. Une fois appliqué, le prochain acteur verra les threads déjà épinglés
dans `/proc` et ne les comptera plus comme libres. `/run/` est un tmpfs (recréé au
boot), donc pas de verrou fantôme entre reboots.

**Pourquoi pas un daemon ?** Un daemon ajoute une dépendance de démarrage, une
surface de crash, un mécanisme de restart. Le `flock` est un primitif noyau, il ne
peut pas tomber en panne.

### 3.6 Le claims registry : pour les acteurs non-QEMU

Les threads QEMU sont découvrables via `/proc`. Mais les containers Podman ou les
outils opérateurs ne le sont pas de cette façon.

**Idée : un fichier de claims** où chaque acteur non-QEMU s'enregistre avec son
label, son PID et ses cœurs. Un claim expire automatiquement quand le processus
meurt — le pool vérifie la vivacité des PIDs à chaque lecture. Les IRQs NIC ne
passent pas par ce mécanisme : elles n'ont pas de PID et le noyau expose déjà leur
état directement.

### 3.7 Les outils de contrôle

Trois interfaces sont nécessaires pour couvrir tous les acteurs :

- **CLI opérateur** : voir l'état du pool (quels cœurs sont pris et par qui),
  réclamer des cœurs pour un processus courant, étaler les workloads sur les paires
  HT disponibles.
- **Helpers containers** : les containers sont multi-processus ; un simple taskset
  sur le PID principal ne suffit pas. L'enforcement doit passer par les cgroups
  systemd pour contraindre tous les processus du service. Un helper
  `pin`/`unpin` s'intègre dans les hooks `ExecStartPost=`/`ExecStopPost=` du
  quadlet.
- **Wrapper processus tiers** : pour les binaires qu'on ne peut pas modifier, un
  wrapper réclame les cœurs, s'y épingle, puis lance la commande — l'enfant hérite
  de l'affinité via `fork`/`exec`.

### 3.8 Le hook libvirt : le déclencheur pour les VMs

**Qu'est-ce qu'un hook libvirt ?**
libvirt appelle automatiquement tout script placé dans `/etc/libvirt/hooks/qemu.d/`
à chaque événement du cycle de vie d'une VM, avec le nom de la VM, l'opération,
et le XML complet du domaine sur stdin.

**Pourquoi un hook plutôt que le XML ?**
Un hook s'exécute au moment du démarrage, sur le nœud hôte réel, avec une vue live
de l'occupation des cœurs. C'est le seul endroit où on peut faire une allocation
dynamique.

**Ce que doit faire le hook :**
- Réagir aux événements `started/begin` (démarrage normal) et `started/incoming`
  (migration entrante) ; ignorer tout le reste
- Lire le profil de pinning depuis les métadonnées RBD, avec fallback sur un profil
  par défaut si absent
- Allouer sous flock, appliquer le pinning sur chaque groupe de threads QEMU
- **Ne jamais retourner un code non-nul** — une erreur dans le hook ne doit pas
  empêcher le démarrage de la VM ; on logue et on laisse passer

### 3.9 Stratégies d'allocation et compaction

La façon dont les cœurs libres sont distribués entre les threads influence
l'efficacité et l'isolation HT :

| Stratégie | Comportement |
|--------|--------------|
| `spreading` | Un thread par cœur physique avant de passer à la paire suivante — meilleure isolation HT (**par défaut**) |
| `packing` | Remplit les deux siblings d'une paire avant de passer à la suivante — moins de cœurs physiques actifs |
| `repacking` | Comme `spreading`, mais compacte d'abord les threads existants pour libérer des paires physiques entières avant d'allouer en `exclusive_physical` |

La compaction (`repacking`) est utile quand le pool de paires physiques est épuisé
alors que des paires "à moitié occupées" (un sibling occupé, l'autre libre) existent.
En déplaçant un thread d'une paire vers le sibling libre d'une autre, on libère
une paire entière pour le nouvel acteur.

Une commande `spread` à la demande permet d'inverser le packing manuellement : elle
identifie les paires où deux threads cohabitent et en déplace un vers une paire libre.

### 3.10 Observabilité : export Prometheus

Pour superviser l'état du pool et détecter les dégradations d'allocation, le système
doit exporter ses métriques vers Prometheus. L'approche naturelle est un textfile
collector : une commande d'export tournant sur timer écrit un fichier `.prom` dans
le répertoire surveillé par le node_exporter, sans modifier l'infrastructure de
collecte existante.

Les métriques utiles sont : cœurs libres, paires physiques libres, acteurs actifs
par type, compteur de dégradations d'allocation, et état courant des acteurs en mode
dégradé (pour distinguer "isolation RT perdue" de "simple bruit HT"). Un dashboard
Grafana permet de visualiser qui occupe quoi sur la carte CPU.

---

## 4. Découpage en étapes testables

Chaque étape peut être développée et testée indépendamment. Les étapes 1 à 4 forment
le cœur du système (VM pinning complet) ; les étapes 5 à 8 sont des extensions.

---

### Étape 1 — Topologie CPU et pool de cœurs libres

**Objectif :** lire la topologie du nœud et calculer les cœurs disponibles.

Lire les cœurs isolés et les paires HT depuis `/sys`, scanner `/proc` pour
identifier les threads déjà épinglés, lire les affinités IRQ NIC passivement.
Exposer `free_logical()` et `free_physical()`.

**Comment tester :**
```bash
python3 -m pytest tests/test_topology.py tests/test_pool.py -v
```

**Critère de réussite :** avec 2 VMs simulées occupant les cœurs 4 et 6, et une IRQ
NIC sur le cœur 8, `free_logical()` retourne `[5, 7, 9, 10, 11]`.

---

### Étape 2 — Moteur d'allocation

**Objectif :** mapper des spécifications de besoins à des cœurs concrets.

Logique pure (pas d'I/O). Gère les trois niveaux d'isolation et les fallbacks.
Implémente les stratégies `spreading`, `packing`, `repacking`.

**Comment tester :**
```bash
python3 -m pytest tests/test_allocator.py -v
```

Scénario de référence : guest2 occupe (4,5) et (6,7) ; guest1 demande 2 vCPUs
`exclusive_physical` + émulateur `exclusive_logical` + vhost `exclusive_logical`.
Résultat attendu : vCPU/0 sur 8, vCPU/1 sur 10, émulateur et vhost en housekeeping
(pool RT épuisé), warnings générés.

---

### Étape 3 — Découverte des threads QEMU et application du pinning

**Objectif :** trouver les TIDs des threads d'une VM et leur appliquer le pinning.

Trouver le PID QEMU dans `/proc`, classifier ses threads par rôle (`comm`), gérer
la découverte en deux phases (polling vCPUs, puis fenêtre de grâce pour les vhost).
Appliquer taskset + chrt dans le bon ordre : **vCPUs → émulateur → vhost → iothreads**.

**Comment tester :**
```bash
# Le hook lit le XML du domaine sur stdin — le fournir explicitement :
virsh dumpxml <vm> | /usr/bin/seapath-qemu-hook <vm> started begin -
```

**Critère de réussite :** après exécution du hook, `cat /proc/<tid>/status | grep
Cpus_allowed_list` confirme l'affinité attendue pour chaque thread QEMU.

---

### Étape 4 — Hook libvirt complet et flock

**Objectif :** assembler les étapes 1-3 dans un hook libvirt fonctionnel avec
sérialisation.

Dispatcher les événements libvirt, tenir le flock pendant toute la fenêtre
découverte → allocation → pinning, charger le profil depuis RBD avec fallback,
ne jamais retourner un code non-nul.

**Critère de réussite :** démarrer deux VMs simultanément — elles ne doivent pas se
retrouver sur les mêmes cœurs.

---

### Étape 5 — Claims registry et outillage opérateur

**Objectif :** permettre aux containers et outils admin de s'enregistrer dans le
même système d'allocation, et donner à l'opérateur une vue d'ensemble.

Claims auto-expirants sur mort du processus, intégrés dans le pool. Outillage
opérateur pour voir l'état du pool, réclamer/libérer des cœurs, étaler les
workloads entre paires HT.

**Critère de réussite :** une VM qui démarre après qu'un container a réclamé le
cœur 8 n'obtient pas le cœur 8.

---

### Étape 6 — Intégration containers via systemd/quadlet

**Objectif :** remplacer les `CPUAffinity=` statiques des unités quadlet par une
allocation dynamique au niveau cgroup.

Un simple taskset sur le PID principal ne suffit pas pour les services
multi-processus — l'enforcement doit passer par les cgroups systemd. Des helpers
`pin`/`unpin` s'intègrent dans `ExecStartPost=`/`ExecStopPost=`.

**Critère de réussite :** tous les PIDs d'un service contraint ont bien l'affinité
attendue, y compris les processus enfants créés après le pin.

---

### Étape 7 — Observabilité Prometheus

**Objectif :** exporter l'état du pool et les événements de dégradation vers
Prometheus pour la supervision et l'alerting.

Timer systemd qui déclenche l'export régulièrement, métriques de pool (cœurs
libres, acteurs actifs) et de dégradation (compteur cumulé, acteurs couramment
dégradés avec leur sévérité). Dashboard Grafana avec carte CPU.

---

### Étape 8 — Intégration dans `vm_manager`

**Objectif :** permettre de définir le profil de pinning au moment du déploiement
d'une VM, sans avoir à lancer `rbd image-meta set` à la main après coup.

`vm_manager` (dépôt [seapath/vm_manager](https://github.com/seapath/vm_manager))
écrit toutes les métadonnées RBD à la création et au clone d'une VM. Y ajouter la
gestion du profil de pinning comme une métadonnée comme les autres, avec
propagation automatique au clone et commandes de lecture/écriture du profil d'une
VM existante.

---

## 5. Ce qui n'est PAS dans le scope de ce hackathon

- Les notifications push ("préviens-moi quand un cœur se libère") — pas de cas
  d'usage identifié
- La gestion des NUMA nodes — SEAPATH cible aujourd'hui des serveurs mono-socket
- La migration à chaud des profils (changer le profil d'une VM en cours d'exécution)

---

## 6. Références et ressources

- [SEAPATH sur GitHub](https://github.com/seapath)
- [LF Energy SEAPATH Wiki](https://lf-energy.atlassian.net/wiki/spaces/SEAP)
- `man 7 cpuset` — semantics of CPU affinity in Linux
- `man 1 taskset` — affinité CPU par thread
- `man 1 chrt` — politiques d'ordonnancement RT
- `man 2 flock` — verrouillage de fichier
- [libvirt hooks](https://libvirt.org/hooks.html) — protocole d'appel du hook QEMU
- [Linux isolcpus](https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html) — paramètre noyau `isolcpus=`
- [PREEMPT_RT](https://wiki.linuxfoundation.org/realtime/start) — patch temps-réel Linux
