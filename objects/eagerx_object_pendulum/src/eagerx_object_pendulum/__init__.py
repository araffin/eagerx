# HACK way to make pycharm find imports.
# from os import path as os_path
# from pkgutil import extend_path
# from sys import path as sys_path
#
# __extended_path = '/home/bas/eagerx_ws/devel/lib/python2.7/dist-packages/eagerx_object_pendulum'.split(';')
# for p in reversed(__extended_path):
#     sys_path.insert(0, p)
#     del p
# del sys_path
#
# __path__ = extend_path(__path__, __name__)
# del extend_path
#
# __execfiles = []
# for p in __extended_path:
#     src_init_file = os_path.join(p, __name__ + '.py')
#     if os_path.isfile(src_init_file):
#         __execfiles.append(src_init_file)
#     else:
#         src_init_file = os_path.join(p, __name__, '__init__.py')
#         if os_path.isfile(src_init_file):
#             __execfiles.append(src_init_file)
#     del src_init_file
#     del p
# del os_path
# del __extended_path


