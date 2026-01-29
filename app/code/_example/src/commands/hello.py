class HelloCommand:
    @property
    def name(self):
        return "example:hello"

    @property
    def help(self):
        return "Print a greeting from the example module"

    def configure(self, parser):
        parser.add_argument("--name", default="World", help="Name to greet")

    def execute(self, args):
        print(f"Hello, {args.name}! This is the example module.")
