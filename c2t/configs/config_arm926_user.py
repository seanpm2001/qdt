c2t_cfg = C2TConfig(
    rsp_target = DebugClient(
        march = "arm926",
        new_rsp = get_new_rsp(
            regs = ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8",
                    "r9", "r10", "r11", "r12", "sp", "lr", "pc",
                    "xpsr", "msp", "psp", "special"],
            pc = "pc",
            regsize = 32
        ),
        user = True,
        sp = "sp"
    ),
    qemu = DebugServer(Run(
        executable = "/usr/bin/qemu-arm",
        args = "-singlestep -g {port} {bin}"
    )),
    gdbserver = DebugServer(Run(
        executable = "/usr/bin/gdbserver",
        args = "localhost:{port} {bin}"
    )),
    target_compiler = TestBuilder(
        Run( # compiler
            executable = "/usr/bin/arm-linux-gnueabihf-gcc",
            args = "-O0 -g -mcpu=arm926ej-s {src} -o {bin} -static"
        ),
    ),
    oracle_compiler = TestBuilder(
        Run( # compiler
            executable = "/usr/bin/gcc",
            args = "-g -O0 {src} -o {bin}"
        )
    )
)
