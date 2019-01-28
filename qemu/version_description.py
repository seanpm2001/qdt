__all__ = [
    "ProcessingUntrackedFile"
  , "ProcessingModifiedFile"
  , "QVCWasNotInitialized"
  , "BadBuildPath"
  , "QVCIsNotReady"
  , "QemuVersionDescription"
  , "qvd_get"
  , "qvds_load"
  , "qvd_load_with_cache"
  , "qvds_load_with_cache"
  , "qvds_init_cache"
  , "forget_build_path"
  , "load_build_path_list"
  , "account_build_path"
]

from source import (
    SourceTreeContainer,
    Header,
    Macro
)
from common import (
    fixpath,
    CommitDesc,
    mlget as _,
    callco,
    remove_file,
    execfile,
    pythonize
)
from json import (
    load
)
from .version import (
    QVHDict,
    initialize_version,
    qemu_heuristic_db,
    calculate_qh_hash,
    get_vp
)
from os import (
    listdir
)
from os.path import (
    sep,
    join,
    isfile
)
from .pci_ids import (
    PCIId,
    PCIClassification
)
from git import (
    Repo
)
from six import (
    u
)
from tempfile import (
    mkdtemp
)
from shutil import (
    rmtree
)
from subprocess import (
    Popen
)

bp_file_name = "build_path_list"

# Two level dict:
# 1. path (of Qemu Git repo)
# 2. Qemu version (SHA1 id of Git commit)
qvd_reg = None

class ProcessingUntrackedFile(RuntimeError):
    def __init__(self, file_name):
        super(ProcessingUntrackedFile, self).__init__(file_name)

    def __str__(self):
        return (_("Source has untracked file: %s.") % self.args[0]).get()

class ProcessingModifiedFile(RuntimeError):
    def __init__(self, file_name):
        super(ProcessingModifiedFile, self).__init__(file_name)

    def __str__(self):
        return (_("Source has modified file: %s.") % self.args[0]).get()

def load_build_path_list():
    global qvd_reg

    if qvd_reg is not None:
        return

    qvd_reg = {}

    if not isfile(bp_file_name):
        return

    with open(bp_file_name) as f:
        build_path_list = f.readlines()

    for val in build_path_list:
        v = val.rstrip()
        qvd_reg[v] = {}

def account_build_path(path):
    load_build_path_list()

    if path in qvd_reg.keys():
        return
    if not isfile(bp_file_name):
        f = open(bp_file_name, 'w')
    else:
        f = open(bp_file_name, 'a')

    f.write(path + "\n")
    f.close()

    qvd_reg[path] = {}

def forget_build_path(path):
    load_build_path_list()

    if not path in qvd_reg.keys():
        raise RuntimeError("%s is not registered." % path)

    del qvd_reg[path]

    with open(bp_file_name, 'w') as f:
        f.write("\n".join(qvd_reg.keys()))

def qvd_get(path, version = None):
    load_build_path_list()

    if path is None:
        raise BadBuildPath("Build path is None.")

    try:
        qvds = qvd_reg[path]
    except KeyError:
        # before accounting because it can raise an exception
        qvd = QemuVersionDescription(path, version = version)
        account_build_path(path)
        qvd_reg[path][qvd.commit_sha] = qvd
        return qvd

    if version is None and qvds:
        # Legacy behavior. Return QVD for HEAD if version is omitted.
        # Note, Git repository at this path can be obtained from any QVD.
        version = next(iter(qvds.values())).repo.head.commit.hexsha

    try:
        return qvds[version]
    except KeyError:
        qvd = QemuVersionDescription(path, version = version)
        # Version aliasing is possible. SHA1 is an invariant. Return existing
        # QVD instead of just created one.
        return qvds.setdefault(qvd.commit_sha, qvd)

def qvd_load_with_cache(build_path, version = None):
    qvd = qvd_get(build_path, version = version)
    qvd.init_cache()
    return qvd

def qvds_load():
    load_build_path_list()

    for path in list(qvd_reg):
        qvd_get(path)

def qvds_init_cache():
    if qvd_reg is None:
        return

    for qvds in qvd_reg.values():
        for v in qvds:
            if v.qvc is None:
                v.init_cache()

def qvds_load_with_cache():
    qvds_load()
    qvds_init_cache()

class QemuCommitDesc(CommitDesc):
    def __init__(self, sha, parents, children):
        super(QemuCommitDesc, self).__init__(sha, parents, children)

        # dict of QEMUVersionParameterDescription new_value parameters
        self.param_nval = {}
        # dict of QEMUVersionParameterDescription old_value parameters
        self.param_oval = {}

class QemuVersionCache(object):
    current = None

    def __init__(self,
                 list_headers = None,
                 device_tree = None,
                 known_targets = None,
                 version_desc = None,
                 pci_classes = None
    ):
        self.device_tree = device_tree
        self.known_targets = known_targets
        self.list_headers = list_headers
        self.version_desc = version_desc

        # Create source tree container
        self.stc = SourceTreeContainer()
        self.pci_c = PCIClassification() if pci_classes is None else pci_classes

    def co_computing_parameters(self, repo, version):
        print("Build QEMU Git graph ...")
        self.commit_desc_nodes = {}
        yield QemuCommitDesc.co_build_git_graph(repo, self.commit_desc_nodes)
        print("QEMU Git graph was built")

        yield self.co_propagate_param()

        c = self.commit_desc_nodes[repo.commit(version).hexsha]
        param = self.version_desc = QVHDict()
        for k, v in c.param_nval.items():
            param[k] = v
        for k, v in c.param_oval.items():
            param[k] = v

    def co_propagate_param(self):
        vd = qemu_heuristic_db
        vd_list = []

        unknown_vd_keys = set()
        for k in vd.keys():
            if k in self.commit_desc_nodes:
                vd_list.append((k, self.commit_desc_nodes[k].num))
            else:
                unknown_vd_keys.add(k)
                print("WARNING: Unknown SHA1 %s in QEMU heuristic database" % k)

        sorted_tuple = sorted(vd_list, key = lambda x: x[1])
        sorted_vd_keys = [t[0] for t in sorted_tuple]

        yield True

        # first, need to propagate the new labels
        print("Propagation params in graph of commit's description ...")
        yield self.co_propagate_new_param(sorted_vd_keys, vd)
        yield self.co_propagate_old_param(sorted_vd_keys, unknown_vd_keys, vd)
        print("Params in graph of commit's description were propagated")

    def co_propagate_new_param(self, sorted_vd_keys, vd):
        '''This method propagate QEMUVersionParameterDescription.new_value
        in graph of commits. It must be called before old_value propagation.

        sorted_vd_keys: keys of qemu_heuristic_db sorted in ascending order
        by num of QemuCommitDesc. It's necessary to optimize the graph
        traversal.
        vd: qemu_heuristic_db
        '''

        # iterations to yield
        i2y = QVD_HP_IBY

        for key in sorted_vd_keys:
            cur_vd = vd[key]
            cur_node = self.commit_desc_nodes[key]
            for vpd in cur_vd:
                cur_node.param_nval[vpd.name] = vpd.new_value

            if i2y == 0:
                yield True
                i2y = QVD_HP_IBY
            else:
                i2y -= 1

        # vd_keys_set is used to accelerate propagation
        vd_keys_set = set(sorted_vd_keys)

        # old_val contains all old_value that are in ancestors
        old_val = {}
        for key in sorted_vd_keys:
            stack = [self.commit_desc_nodes[key]]
            for vpd in vd[key]:
                try:
                    old_val[vpd.name].append(vpd.old_value)
                except KeyError:
                    old_val[vpd.name] = [vpd.old_value]
            while stack:
                cur_node = stack.pop()
                for c in cur_node.children:
                    if c.sha in vd_keys_set:
                        # if the child is vd, only the parameters that are not
                        # in vd's param_nval are added
                        for p in cur_node.param_nval:
                            if p not in c.param_nval:
                                c.param_nval[p] = cur_node.param_nval[p]
                        # no need to add element to stack, as it's in the sorted_vd_keys
                    else:
                        # the child is't vd
                        for p in cur_node.param_nval:
                            if p in c.param_nval:
                                if cur_node.param_nval[p] != c.param_nval[p]:
                                    exc_raise = False
                                    if p in old_val:
                                        if cur_node.param_nval[p] not in old_val[p]:
                                            if c.param_nval[p] in old_val[p]:
                                                c.param_nval[p] = cur_node.param_nval[p]
                                                stack.append(c)
                                            else:
                                                exc_raise = True
                                    else:
                                        exc_raise = True
                                    if exc_raise:
                                        raise Exception("Contradictory definition of param " \
"'%s' in commit %s (%s != %s)" % (p, c.sha, cur_node.param_nval[p], c.param_nval[p])
                                        )
                            else:
                                c.param_nval[p] = cur_node.param_nval[p]
                                stack.append(c)

                if i2y == 0:
                    yield True
                    i2y = QVD_HP_IBY
                else:
                    i2y -= 1

    def co_propagate_old_param(self, sorted_vd_keys, unknown_vd_keys, vd):
        '''This method propagate QEMUVersionParameterDescription.old_value
        in graph of commits. It must be called after new_value propagation.

        sorted_vd_keys: keys of qemu_heuristic_db sorted in ascending order
        by num of QemuCommitDesc. It's necessary to optimize the graph
        traversal.

        unknown_vd_keys: set of keys which are not in commit_desc_nodes.

        vd: qemu_heuristic_db
        '''

        # message for exceptions
        msg = "Conflict with param '%s' in commit %s (old_val (%s) != old_val (%s))"

        # iterations to yield
        i2y = QVD_HP_IBY

        # Assume unknown SHA1 corresponds to an ancestor of a known node.
        # Therefore, old value must be used for all commits.
        for commit in self.commit_desc_nodes.values():
            for vd_keys in unknown_vd_keys:
                self.init_commit_old_val(commit, vd[vd_keys])

                i2y -= 1
                if not i2y:
                    yield True
                    i2y = QVD_HP_IBY

        vd_keys_set = set(sorted_vd_keys)
        visited_vd = set()
        for key in sorted_vd_keys[::-1]:
            stack = []
            # used to avoid multiple processing of one node
            visited_nodes = set([key])
            visited_vd.add(key)

            node = self.commit_desc_nodes[key]
            for p in node.parents:
                stack.append(p)

                # propagate old_val from node to their parents
                p.param_oval.update()
                for param, oval in node.param_oval.items():
                    try:
                        other = p.param_oval[param]
                    except KeyError:
                        p.param_oval[param] = oval
                    else:
                        if other != oval:
                            raise Exception(msg % (param, p.sha, oval, other))

                # init old_val of nodes that consist of vd's parents
                # and check conflicts
                self.init_commit_old_val(p, vd[key])

                i2y -= 1
                if not i2y:
                    yield True
                    i2y = QVD_HP_IBY

            while stack:
                cur_node = stack.pop()
                visited_nodes.add(cur_node.sha)

                for commit in cur_node.parents + cur_node.children:
                    if commit.sha in visited_nodes:
                        continue
                    for param_name in cur_node.param_oval:
                        if param_name in commit.param_nval:
                            continue
                        elif param_name in commit.param_oval:
                            if commit.param_oval[param_name] != cur_node.param_oval[param_name]:
                                raise Exception(msg % (
param_name, commit.sha, commit.param_oval[param_name], cur_node.param_oval[param_name]
                                ))
                        else:
                            commit.param_oval[param_name] = cur_node.param_oval[param_name]
                            if commit.sha not in vd_keys_set:
                                stack.append(commit)
                            # if we have visited vd before, it is necessary
                            # to propagate the param, otherwise we do it
                            # in the following iterations of the outer loop
                            elif commit.sha in visited_vd:
                                stack.append(commit)

                i2y -= 1
                if not i2y:
                    yield True
                    i2y = QVD_HP_IBY

    def init_commit_old_val(self, commit, vd):
        # messages for exceptions
        msg1 = "Conflict with param '%s' in commit %s (old_val (%s) != new_val (%s))"
        msg2 = "Conflict with param '%s' in commit %s (old_val (%s) != old_val (%s))"

        for param in vd:
            if param.name in commit.param_nval:
                if commit.param_nval[param.name] != param.old_value:
                    raise Exception(msg1 % (
param.name, commit.sha, param.old_value, commit.param_nval[param.name]
                    ))
            elif param.name in commit.param_oval:
                if commit.param_oval[param.name] != param.old_value:
                    raise Exception(msg2 % (
param.name, commit.sha, param.old_value, commit.param_oval[param.name]
                    ))
            else:
                commit.param_oval[param.name] = param.old_value

    __pygen_deps__ = ("pci_c",)

    def __gen_code__(self, gen):
        gen.reset_gen(self)

        gen.gen_field("device_tree = ")
        gen.pprint(self.device_tree)

        gen.gen_field("known_targets = ")
        gen.pprint(self.known_targets)

        gen.gen_field("list_headers = ")
        gen.pprint(self.list_headers)

        gen.gen_field("version_desc = ")
        gen.pprint(self.version_desc)

        gen.gen_field("pci_classes = " + gen.nameof(self.pci_c))

        gen.gen_end()

    # The method made the cache active.
    def use(self):
        self.stc.set_cur_stc()
        PCIId.db = self.pci_c

        previous = QemuVersionCache.current
        QemuVersionCache.current = self
        return previous

class BadBuildPath(ValueError):
    pass

class QVCWasNotInitialized(RuntimeError):
    pass

class QVCIsNotReady(RuntimeError):
    pass

# Iterations Between Yields of Device Tree Macros adding task
QVD_DTM_IBY = 100
# Iterations Between Yields of Heuristic Propagation task
QVD_HP_IBY = 100
# Iterations Between Yields of Check Modified Files task
QVD_CMF_IBY = 100
# Iterations Between Yields of Check Untracked Files task
QVD_CUF_IBY = 100

QVD_QH_HASH = "qh_hash"

class QemuVersionDescription(object):
    current = None

    def __init__(self, build_path, version = None):
        config_host_path = join(build_path, 'config-host.mak')
        if not isfile(config_host_path):
            forget_build_path(build_path)
            raise BadBuildPath("%s does not exists." % config_host_path)

        self.build_path = build_path

        config_host_f = open(config_host_path)
        config_host = config_host_f.read()
        config_host_f.close()

        self.src_path = fixpath(QemuVersionDescription.ch_lookup(
            config_host,
            "SRC_PATH"
        ))
        self.target_list = fixpath(QemuVersionDescription.ch_lookup(
            config_host,
            "TARGET_DIRS"
        ))

        # Get SHA
        self.repo = Repo(self.src_path)

        if version is None:
            c = self.repo.head.commit
        else:
            c = self.repo.commit(version)

        self.commit_sha = c.hexsha

        VERSION = c.tree["VERSION"]
        self.qemu_version = VERSION.data_stream.read().strip().decode()

        print("Qemu version is {}".format(self.qemu_version))

        self.include_paths = (
            "include",
            "tcg"
        )

        self.include_abs_paths = list(
            join(self.src_path, d) for d in self.include_paths
        )

        self.qvc = None
        self.qvc_is_ready = False

    # The method made the description active
    def use(self):
        if self.qvc is None:
            self.init_cache()
        self.qvc.use()

        previous = QemuVersionDescription.current
        QemuVersionDescription.current = self
        return previous

    def init_cache(self):
        callco(self.co_init_cache())

    def forget_cache(self):
        if self.qvc is None:
            raise QVCWasNotInitialized()
        if not self.qvc_is_ready:
            raise QVCIsNotReady(
                "Attempt to forget QVC which is not ready yet."
            )
        self.qvc = None
        self.qvc_is_ready = False

    def remove_cache(self):
        if self.qvc:
            self.qvc = None
            self.qvc_is_ready = False
            remove_file(self.qvc_path)

    def co_init_cache(self):
        if self.qvc is not None:
            print("Multiple QVC initialization " + self.src_path)
            self.qvc = None

        qvc_file_name = u"qvc_" + self.commit_sha + u".py"
        qvc_path = self.qvc_path = join(self.build_path, qvc_file_name)

        qemu_heuristic_hash = calculate_qh_hash()

        yield True

        if not isfile(qvc_path):
            self.qvc = QemuVersionCache()

            # Check out Qemu source to a temporary directory and analyze it
            # there. This avoids problems with user changes in main working
            # directory.

            tmp_work_dir = mkdtemp("qdt-qemu-%s" % self.commit_sha)

            print("Checking out temporary source tree in %s" % tmp_work_dir)

            # Note. Alternatively, checking out can be performed without
            # cloning. Instead, a magic might be casted on GIT_DIR and
            # GIT_WORK_TREE environment variables. But, this approach resets
            # staged files in src_path repository which can be inconvenient
            # for a user.
            # Current approach uses "-s" (--shared) option to avoid copying
            # of history and "-n" (--no-checkout) to avoid redundant checking
            # out of src_path repo HEAD. Therefore, overhead of cloning is
            # low enough.

            for cmd in [
                ["git", "clone", "-n", "-s", self.src_path, "."],
                ["git", "checkout", "-f", self.commit_sha]
            ]:

                p = Popen(cmd, cwd = tmp_work_dir)

                while p.returncode is None:
                    yield False
                    p.poll()

                if p.returncode:
                    raise RuntimeError(
                        "Failed to checkout Qemu source: %s" % p.returncode
                    )

            # make new QVC active and begin construction
            prev_qvc = self.qvc.use()
            for path in self.include_paths:
                yield Header.co_build_inclusions(join(tmp_work_dir, path))

            self.qvc.list_headers = self.qvc.stc.create_header_db()

            rmtree(tmp_work_dir)

            yield self.co_gen_device_tree()

            yield self.co_gen_known_targets()

            # gen version description
            yield self.qvc.co_computing_parameters(self.repo, self.commit_sha)
            self.qvc.version_desc[QVD_QH_HASH] = qemu_heuristic_hash

            # Search for PCI Ids
            PCIClassification.build()

            yield True

            pythonize(self.qvc, qvc_path)
        else:
            self.load_cache()
            # make just loaded QVC active
            prev_qvc = self.qvc.use()

            if self.qvc.list_headers is not None:
                yield True

                yield self.qvc.stc.co_load_header_db(self.qvc.list_headers)

            yield True

            # verify that the version_desc is not outdated
            is_outdated = False
            try:
                checksum = self.qvc.version_desc[QVD_QH_HASH]
            except KeyError:
                is_outdated = True
            else:
                if not checksum == qemu_heuristic_hash:
                    is_outdated = True
            if is_outdated:
                yield self.qvc.co_computing_parameters(self.repo, self.commit_sha)
                self.qvc.version_desc[QVD_QH_HASH] = qemu_heuristic_hash
                pythonize(self.qvc, qvc_path)

        yield True

        # set Qemu version heuristics according to current version
        initialize_version(self.qvc.version_desc)

        yield True

        # initialize Qemu types in QVC
        get_vp()["qemu types definer"]()
        get_vp()["msi_init type definer"]()

        if prev_qvc is not None:
            prev_qvc.use()

        self.qvc_is_ready = True

    def load_cache(self):
        if not isfile(self.qvc_path):
            raise Exception("%s does not exists." % self.qvc_path)
        else:
            print("Loading QVC from " + self.qvc_path)
            variables = {}
            context = {
                "QemuVersionCache": QemuVersionCache
            }

            import qemu
            context.update(qemu.__dict__)

            execfile(self.qvc_path, context, variables)

            for v in variables.values():
                if isinstance(v, QemuVersionCache):
                    self.qvc = v
                    break
            else:
                raise Exception(
"No QemuVersionCache was loaded from %s." % self.qvc_path
                )
            self.qvc.version_desc = QVHDict(self.qvc.version_desc)

    def co_check_modified_files(self):
        # A diff between the index and the working tree
        modified_files = set()

        # index.diff(None) returns diff between index and working directory
        for e in self.repo.index.diff(None) + self.repo.index.diff('HEAD'):
            abs_path = join(u(self.src_path), e.a_path)
            for include in self.include_abs_paths:
                if abs_path.startswith(include + sep):
                    modified_files.add(abs_path[len(include)+1:])

        yield True

        i2y = QVD_CMF_IBY
        for e in self.qvc.list_headers:
            if e['path'] in modified_files:
                raise ProcessingModifiedFile(e['path'])

            if i2y == 0:
                yield True
                i2y = QVD_CMF_IBY
            else:
                i2y -= 1

    def co_check_untracked_files(self):
        i2y = QVD_CUF_IBY
        for path in self.repo.untracked_files:
            abs_path = join(self.src_path, path)
            for include in self.include_abs_paths:
                if abs_path.startswith(include + sep):
                    raise ProcessingUntrackedFile(path)

                if i2y == 0:
                    yield True
                    i2y = QVD_CUF_IBY
                else:
                    i2y -= 1

    @staticmethod
    def ch_lookup(config_host, parameter):
        indx_begin = config_host.find(parameter)
        if indx_begin == -1:
            raise Exception('Parameter "{}" does not exists.'.format(
                parameter
            ))
        indx_end = config_host.find("\n", indx_begin)

        option = config_host[indx_begin:indx_end]
        l = option.split("=")
        if len(l) > 1:
            return l[1]
        else:
            return None

    # TODO: get dt from qemu

    def co_gen_device_tree(self):
        dt_db_fname = join(self.build_path, "dt.json")
        if  isfile(dt_db_fname):
            print("Loading Device Tree from " + dt_db_fname + "...")
            dt_db_reader = open(dt_db_fname, "r")
            self.qvc.device_tree = load(dt_db_reader)
            dt_db_reader.close()
            print("Device Tree was loaded from " + dt_db_fname)
            yield True

            print("Adding macros to device tree ...")
            yield self.co_add_dt_macro(self.qvc.device_tree)
            print("Macros were added to device tree")
        else:
            self.qvc.device_tree = None

    def co_gen_known_targets(self):
        print("Making known targets set...")
        dconfigs = join(self.src_path, "default-configs")
        kts = set()
        for config in listdir(dconfigs):
            yield True
            for suffix in ["-softmmu.mak", "-linux-user.mak", "-bsd-user.mak"]:
                if config.endswith(suffix):
                    kts.add(config[:-len(suffix)])
                    break
        print("Known targets set was made")
        self.qvc.known_targets = kts

    def co_add_dt_macro(self, list_dt, text2macros = None):
        # iterations to yield
        i2y = QVD_DTM_IBY

        if text2macros is None:
            print("Building text to macros mapping...")

            text2macros = {}
            for t in self.qvc.stc.reg_type.values():
                if i2y == 0:
                    yield True
                    i2y = QVD_DTM_IBY
                else:
                    i2y -= 1

                if not isinstance(t, Macro):
                    continue

                text = t.text
                try:
                    aliases = text2macros[text]
                except KeyError:
                    text2macros[text] = [t.name]
                else:
                    aliases.append(t.name)

            print("The mapping was built.")

        # Use the mapping to build "list_dt"
        for dict_dt in list_dt:
            if i2y == 0:
                yield True
                i2y = QVD_DTM_IBY
            else:
                i2y -= 1

            dt_type = dict_dt["type"]
            dt_type_text = '"' + dt_type + '"'
            try:
                aliases = text2macros[dt_type_text]
            except KeyError:
                # No macros for this type
                if "macro" in dict_dt:
                    print(
"No macros for type %s now, removing previous cache..." % dt_type_text
                    )
                    del dict_dt["macro"]
            else:
                if "macro" in dict_dt:
                    print("Override macros for type %s" % dt_type_text)
                dict_dt["macro"] = list(aliases)

            try:
                dt_properties = dict_dt["property"]
            except KeyError:
                pass # QOM type have no properties
            else:
                for dt_property in dt_properties:
                    if i2y == 0:
                        yield True
                        i2y = QVD_DTM_IBY
                    else:
                        i2y -= 1

                    dt_property_name_text = '"' + dt_property["name"] + '"'
                    try:
                        aliases = text2macros[dt_property_name_text]
                    except KeyError:
                        # No macros for this property
                        if "macro" in dt_property:
                            print(
"No macros for property %s of type %s, removing previous cache..." % (
    dt_property_name_text, dt_type_text
)
                            )
                            del dt_property["macro"]
                        continue
                    if "macro" in dt_property:
                        print("Override macros for property %s of type %s" % (
                            dt_property_name_text, dt_type_text
                        ))
                    dt_property["macro"] = list(aliases)

            if "children" in dict_dt:
                yield self.co_add_dt_macro(dict_dt["children"], text2macros)
