import subprocess


IN = "protocol=https\nhost=github.com\nusername=sean\n\n"


try:
    proc = subprocess.run(
        "git credential fill".split(" "),
        input=IN,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    print(proc.stdout.splitlines())
except subprocess.CalledProcessError as e:
    print("ERROR: ", e)
except KeyboardInterrupt:
    print("Cancelled")

print("DONE")
