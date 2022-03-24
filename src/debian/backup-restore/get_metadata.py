import rbd,rados,sys
cluster = rados.Rados(conffile='/etc/ceph/ceph.conf')
cluster.connect()
ioctx = cluster.open_ioctx('rbd')
image = rbd.Image(ioctx, "system_"+sys.argv[1])
k = dict(image.metadata_list()).keys()
for i in k:
  print(i)

