from qemu import \
    MachineNode, \
    QProject

from gui_proj_ht import \
    GUIProjectHistoryTracker

from common import \
    History

class GUIProject(QProject):
    def __init__(self, layouts = [], build_path = None, **kw):
        QProject.__init__(self, **kw)

        self.build_path = build_path
        self.layouts = layouts
        self.pht = GUIProjectHistoryTracker(self, History())

    def add_layout(self, desc_name, layout):
        self.layouts.append((desc_name, layout))

    def delete_layouts(self, desc_name):
        # filter out existing layouts for the description
        new_layouts = [
            (name, l) for name, l in self.layouts if name != desc_name
        ]
        self.layouts = new_layouts

    # replaces all layouts for description with new layout
    def set_layout(self, desc_name, layout):
        self.delete_layouts(desc_name)
        self.add_layout(desc_name, layout)

    def set_layouts(self, desc_name, layouts):
        self.delete_layouts(desc_name)

        for l in layouts:
            self.add_layout(desc_name, l)

    def get_layouts(self, desc_name):
        return [ l for name, l in self.layouts if name == desc_name ]

    def get_machine_descriptions(self):
        return [ d for d in self.descriptions if isinstance(d, MachineNode) ]

    def __children__(self):
        return list(self.descriptions)

    def __gen_code__(self, gen):
        gen.reset_gen(self)
        gen.gen_field("layouts = ")
        gen.pprint(self.layouts)
        gen.gen_field("build_path = " + gen.gen_const(self.build_path))
        gen.gen_field("descriptions = [")
        gen.line()
        gen.push_indent()
        for i, desc in enumerate(self.descriptions):
            if i > 0:
                gen.line(",")
            gen.write(gen.nameof(desc))
        gen.line()
        gen.pop_indent()
        gen.write("]")
        gen.gen_end()
