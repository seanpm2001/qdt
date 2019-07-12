#!/usr/bin/python

from qemu import (
    POp_AddDesc,
    MachineWatcher,
    PCMachineWatcher,
    QOMTreeReverser,
    MachineReverser,
    MachineNode
)
from debug import (
    git_repo_by_dwarf,
    create_dwarf_cache,
    Runtime,
    GitLineVersionAdapter
)
from common import (
    pypath,
    mlget as _,
    pythonize
)
from argparse import (
    SUPPRESS,
    ArgumentDefaultsHelpFormatter,
    ArgumentParser
)
from sys import (
    stderr
)
from os import (
    remove
)
from widgets import (
    GUIProject,
    GUIProjectHistoryTracker,
    asksaveas,
    VarMenu,
    HotKey,
    HotKeyBinding,
    MachineDescriptionSettingsWidget,
    GUITk
)
from six.moves.tkinter_messagebox import (
    showerror
)
from subprocess import (
    Popen
)
# use ours pyrsp
with pypath("pyrsp"):
    from pyrsp.rsp import (
        AMD64
    )
    from pyrsp.utils import (
        find_free_port,
        wait_for_tcp_port
    )

class QArgumentParser(ArgumentParser):

    def error(self, *args, **kw):
        stderr.write("Error in argument string. Ensure that `--` is passed"
            " before QEMU and its arguments.\n"
        )
        super(QArgumentParser, self).error(*args, **kw)


class QEmuWatcherGUI(GUITk):
    "Showing runtime state of machine."

    def __init__(self, pht, runtime):
        GUITk.__init__(self, wait_msec = 1)

        self.title(_("QEmu Watcher"))

        self.pht = pht
        self.rt = runtime

        self.rowconfigure(0, weight = 1)
        self.columnconfigure(0, weight = 1)

        self._killed = False
        self.task_manager.enqueue(self.co_rsp_poller())

        self.hk = hk = HotKey(self)
        hk.add_bindings([
            HotKeyBinding(self._on_save,
                key_code = 39,
                description = _("Save machine"),
                symbol = "S"
            )
        ])

        menubar = VarMenu(self)
        self.config(menu = menubar)

        filemenu = VarMenu(menubar, tearoff = False)
        menubar.add_cascade(label = _("File"), menu = filemenu)

        filemenu.add_command(
            label = _("Save machine"),
            command = self._on_save,
            accelerator = hk.get_keycode_string(self._on_save)
        )
        self._exiting = False
        self.protocol("WM_DELETE_WINDOW", self._on_wm_delete_window)

        pht.watch_changed(self._on_changed)

    def _on_changed(self, op):
        if not isinstance(op, POp_AddDesc):
            return

        for d in self.pht.p.descriptions:
            if isinstance(d, MachineNode):
                break
        else:
            return

        mdsw = MachineDescriptionSettingsWidget(d, self)
        mdsw.grid(row = 0, column = 0, sticky = "NESW")
        mdsw.mw.mdw.var_physical_layout.set(False)
        self.mdsw = mdsw

        # magic with layouts
        self.pht.p.add_layout(d.name, mdsw.gen_layout()).widget = mdsw

        # only one machine is supported
        self.pht.unwatch_changed(self._on_changed)

    def _on_save(self):
        fname = asksaveas(self,
            [(_("QDC GUI Project defining script"), ".py")],
            title = _("Save machine")
        )

        if not fname:
            return

        self.save_project_to_file(fname)

    def try_save_project_to_file(self, file_name):
        try:
            open(file_name, "wb").close()
        except IOError as e:
            if not e.errno == 13: # Do not remove read-only files
                try:
                    remove(file_name)
                except:
                    pass

            showerror(
                title = _("Cannot save project").get(),
                message = str(e)
            )
            return

        self.save_project_to_file(file_name)

    def save_project_to_file(self, file_name):
        project = self.pht.p

        project.sync_layouts()

        # Ensure that all machine nodes are in corresponding lists
        for d in project.descriptions:
            if isinstance(d, MachineNode):
                d.link(handle_system_bus = False)

        pythonize(project, file_name)

    def co_rsp_poller(self):
        yield self.rt.co_run_target()

        self._killed = True

        if self._exiting:
            self.destroy()

    def _on_wm_delete_window(self):
        if self._killed:
            self.destroy()
            return

        # co_rsp_poller will destroy the window after RSP thread ended.
        self._exiting = True
        self.rt.target.exit = True


def main():
    ap = QArgumentParser(
        formatter_class = ArgumentDefaultsHelpFormatter,
        description = "QEMU runtime introspection tool"
    )
    ap.add_argument("-q",
        dest = "qsrc",
        help = "QEMU src directory."
    )
    ap.add_argument("-c", "--connect",
        nargs = "?",
        metavar = "HOST",
        const = "127.0.0.1", # default if `-c` is given without a value
        # Suppress reasons:
        # 1. do not print incorrect default in help by
        #    `ArgumentDefaultsHelpFormatter` (correct is `const`)
        # 2. do not add the attribute to parsed args if the arg is missed
        default = SUPPRESS,
        help = "connect to existing gdbstub (default: %(const)s)"
    )
    ap.add_argument("-p", "--port",
        type = int,
        metavar = "PORT",
        default = 4321,
        help = "start search for unused port from this number"
    )
    ap.add_argument("qarg",
        nargs = "+",
        help = "QEMU executable and arguments to it. Prefix them with `--`."
    )
    args = ap.parse_args()

    # executable
    qemu_cmd_args = args.qarg

    # src directory
    qemu_src_dir = args.qsrc

    # debug info
    qemu_debug = qemu_cmd_args[0]

    dic = create_dwarf_cache(qemu_debug)

    if qemu_src_dir:
        gvl_adptr = GitLineVersionAdapter(qemu_src_dir)
    else:
        try:
            repo = git_repo_by_dwarf(dic.di)
        except ValueError:
            print("No Qemu Git was given. Breakpoint position adaptation is"
                " disabled."
            )
            gvl_adptr = None
        else:
            gvl_adptr = GitLineVersionAdapter(repo)

    qomtr = QOMTreeReverser(dic,
        interrupt = False,
        verbose = True,
        line_adapter = gvl_adptr
    )

    if "-i386" in qemu_debug or "-x86_64" in qemu_debug:
        MWClass = PCMachineWatcher
    else:
        MWClass = MachineWatcher

    mw = MWClass(dic, qomtr.tree,
        interrupt = True,
        line_adapter = gvl_adptr
    )

    proj = GUIProject()
    pht = GUIProjectHistoryTracker(proj, proj.history)

    MachineReverser(mw, pht)

    try:
        qemu_debug_addr_fmt = args.connect + ":%u"
    except AttributeError: # no -c/--connect option
        # auto select free port for gdb-server
        port = find_free_port(args.port)

        qemu_debug_addr = "localhost:%u" % port

        qemu_proc = Popen(
            ["gdbserver", qemu_debug_addr] + qemu_cmd_args
        )
    else:
        port = args.port
        qemu_debug_addr = qemu_debug_addr_fmt % port
        qemu_proc = None

    if not wait_for_tcp_port(port):
        raise RuntimeError("gdbserver does not listen %u" % port)

    qemu_debugger = AMD64(str(port), noack = True)

    rt = Runtime(qemu_debugger, dic)

    qomtr.init_runtime(rt)
    mw.init_runtime(rt)

    # Because pyrsp (with machine reconstruction suite) works in a separate
    # thread, tracker's "changed" notifications are racing with GUI. So, GUI
    # must not watch those notifications. To maintain GUI consistency
    # other project and tracker are created with same history. The GUI is
    # watching this second tracker. A special coroutine working in GUI thread
    # will poll first (master) tracker position and adjust second (slave)
    # tracker updating the GUI without races.
    proj2 = GUIProject()
    # different context (project) but same history
    slave_pht = GUIProjectHistoryTracker(proj2, proj.history)

    def co_syncronizer():
        while True:
            if slave_pht.pos != pht.pos:
                yield True
                slave_pht.do()
            else:
                yield False

    tk = QEmuWatcherGUI(slave_pht, rt)

    tk.task_manager.enqueue(co_syncronizer())

    tk.geometry("1024x1024")
    tk.mainloop()

    qomtr.to_file("qom-by-q.i.dot")

    if qemu_proc is not None:
        qemu_proc.wait()

    if gvl_adptr is not None:
        gvl_adptr.cm.store_cache()


if __name__ == "__main__":
    exit(main())
