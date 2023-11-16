import json
import logging
import os
import random
import re
import shutil
import statistics
import string
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Callable, List, Tuple

import optuna
import prettytable
import testcases
from Crypto.Cipher import AES
from result import TestResult
from termcolor import colored
from testcases import Perspective


def random_string(length: int):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


class MeasurementResult:
    result = TestResult
    details = str


class LogFileFormatter(logging.Formatter):
    def format(self, record):
        msg = super(LogFileFormatter, self).format(record)
        # remove color control characters
        return re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]").sub("", msg)


class InteropRunner:
    _start_time = 0
    test_results = {}
    measurement_results = {}
    compliant = {}
    _implementations = {}
    _servers = []
    _clients = []
    _tests = []
    _measurements = []
    _output = ""
    _log_dir = ""
    _save_files = False

    def __init__(
        self,
        implementations: dict,
        servers: List[str],
        clients: List[str],
        tests: List[testcases.TestCase],
        measurements: List[testcases.Measurement],
        output: str,
        debug: bool,
        save_files=False,
        log_dir="",
    ):
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler(stream=sys.stderr)
        if debug:
            console.setLevel(logging.DEBUG)
        else:
            console.setLevel(logging.INFO)
        logger.addHandler(console)
        self._start_time = datetime.now()
        self._tests = tests
        self._measurements = measurements
        self._servers = servers
        self._clients = clients
        self._implementations = implementations
        self._output = output
        self._log_dir = log_dir
        self._save_files = save_files
        if len(self._log_dir) == 0:
            self._log_dir = "logs_{:%Y-%m-%dT%H:%M:%S}".format(self._start_time)
        if os.path.exists(self._log_dir):
            sys.exit("Log dir " + self._log_dir + " already exists.")
        logging.info("Saving logs to %s.", self._log_dir)
        for server in servers:
            self.test_results[server] = {}
            self.measurement_results[server] = {}
            for client in clients:
                self.test_results[server][client] = {}
                for test in self._tests:
                    self.test_results[server][client][test] = {}
                self.measurement_results[server][client] = {}
                for measurement in measurements:
                    self.measurement_results[server][client][measurement] = {}

    def _is_unsupported(self, lines: List[str]) -> bool:
        return any("exited with code 127" in str(line) for line in lines) or any(
            "exit status 127" in str(line) for line in lines
        )

    def _check_impl_is_compliant(self, name: str) -> bool:
        """check if an implementation return UNSUPPORTED for unknown test cases"""
        if name in self.compliant:
            logging.debug(
                "%s already tested for compliance: %s", name, str(self.compliant)
            )
            return self.compliant[name]

        client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
        www_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_www_")
        certs_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="compliance_certs_")
        downloads_dir = tempfile.TemporaryDirectory(
            dir="/tmp", prefix="compliance_downloads_"
        )

        testcases.generate_cert_chain(certs_dir.name)

        # check that the client is capable of returning UNSUPPORTED
        logging.debug("Checking compliance of %s client", name)
        cmd = (
            "CERTS=" + certs_dir.name + " "
            "TESTCASE_CLIENT=" + random_string(6) + " "
            "SERVER_LOGS=/dev/null "
            "CLIENT_LOGS=" + client_log_dir.name + " "
            "WWW=" + www_dir.name + " "
            "DOWNLOADS=" + downloads_dir.name + " "
            'SCENARIO="simple-p2p --delay=15ms --bandwidth=10Mbps --queue=25" '
            "CLIENT=" + self._implementations[name]["image"] + " "
            "docker-compose up --timeout 0 --abort-on-container-exit -V sim client"
        )
        output = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        if not self._is_unsupported(output.stdout.splitlines()):
            logging.error("%s client not compliant.", name)
            logging.debug("%s", output.stdout.decode("utf-8"))
            self.compliant[name] = False
            return False
        logging.debug("%s client compliant.", name)

        # check that the server is capable of returning UNSUPPORTED
        logging.debug("Checking compliance of %s server", name)
        server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
        cmd = (
            "CERTS=" + certs_dir.name + " "
            "TESTCASE_SERVER=" + random_string(6) + " "
            "SERVER_LOGS=" + server_log_dir.name + " "
            "CLIENT_LOGS=/dev/null "
            "WWW=" + www_dir.name + " "
            "DOWNLOADS=" + downloads_dir.name + " "
            "SERVER=" + self._implementations[name]["image"] + " "
            "docker-compose up -V server"
        )
        output = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        if not self._is_unsupported(output.stdout.splitlines()):
            logging.error("%s server not compliant.", name)
            logging.debug("%s", output.stdout.decode("utf-8"))
            self.compliant[name] = False
            return False
        logging.debug("%s server compliant.", name)

        # remember compliance test outcome
        self.compliant[name] = True
        return True

    def _print_results(self):
        """print the interop table"""
        logging.info("Run took %s", datetime.now() - self._start_time)

        def get_letters(result):
            return "".join(
                [test.abbreviation() for test in cell if cell[test] is result]
            )

        if len(self._tests) > 0:
            t = prettytable.PrettyTable()
            t.hrules = prettytable.ALL
            t.vrules = prettytable.ALL
            t.field_names = [""] + [name for name in self._servers]
            for client in self._clients:
                row = [client]
                for server in self._servers:
                    cell = self.test_results[server][client]
                    res = colored(get_letters(TestResult.SUCCEEDED), "green") + "\n"
                    res += colored(get_letters(TestResult.UNSUPPORTED), "grey") + "\n"
                    res += colored(get_letters(TestResult.FAILED), "red")
                    row += [res]
                t.add_row(row)
            print(t)

        if len(self._measurements) > 0:
            t = prettytable.PrettyTable()
            t.hrules = prettytable.ALL
            t.vrules = prettytable.ALL
            t.field_names = [""] + [name for name in self._servers]
            for client in self._clients:
                row = [client]
                for server in self._servers:
                    cell = self.measurement_results[server][client]
                    results = []
                    for measurement in self._measurements:
                        res = cell[measurement]
                        if not hasattr(res, "result"):
                            continue
                        if res.result == TestResult.SUCCEEDED:
                            results.append(
                                colored(
                                    measurement.abbreviation() + ": " + res.details,
                                    "green",
                                )
                            )
                        elif res.result == TestResult.UNSUPPORTED:
                            results.append(colored(measurement.abbreviation(), "grey"))
                        elif res.result == TestResult.FAILED:
                            results.append(colored(measurement.abbreviation(), "red"))
                    row += ["\n".join(results)]
                t.add_row(row)
            print(t)

    def _export_results(self):
        if not self._output:
            return
        out = {
            "start_time": self._start_time.timestamp(),
            "end_time": datetime.now().timestamp(),
            "log_dir": self._log_dir,
            "servers": [name for name in self._servers],
            "clients": [name for name in self._clients],
            "urls": {
                x: self._implementations[x]["url"]
                for x in self._servers + self._clients
            },
            "tests": {
                x.abbreviation(): {
                    "name": x.name(),
                    "desc": x.desc(),
                }
                for x in self._tests + self._measurements
            },
            "quic_draft": testcases.QUIC_DRAFT,
            "quic_version": testcases.QUIC_VERSION,
            "results": [],
            "measurements": [],
        }

        for client in self._clients:
            for server in self._servers:
                results = []
                for test in self._tests:
                    r = None
                    if hasattr(self.test_results[server][client][test], "value"):
                        r = self.test_results[server][client][test].value
                    results.append(
                        {
                            "abbr": test.abbreviation(),
                            "name": test.name(),  # TODO: remove
                            "result": r,
                        }
                    )
                out["results"].append(results)

                measurements = []
                for measurement in self._measurements:
                    res = self.measurement_results[server][client][measurement]
                    if not hasattr(res, "result"):
                        continue
                    measurements.append(
                        {
                            "name": measurement.name(),  # TODO: remove
                            "abbr": measurement.abbreviation(),
                            "result": res.result.value,
                            "details": res.details,
                        }
                    )
                out["measurements"].append(measurements)

        f = open(self._output, "w")
        json.dump(out, f)
        f.close()

    def _copy_logs(self, container: str, dir: tempfile.TemporaryDirectory):
        r = subprocess.run(
            'docker cp "$(docker-compose --log-level ERROR ps -q '
            + container
            + ')":/logs/. '
            + dir.name,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if r.returncode != 0:
            logging.info(
                "Copying logs from %s failed: %s", container, r.stdout.decode("utf-8")
            )

    def _run_testcase(
        self, server: str, client: str, test: Callable[[], testcases.TestCase]
    ) -> TestResult:
        return self._run_test(server, client, None, test)[0]

    def _run_test(
        self,
        server: str,
        client: str,
        log_dir_prefix: None,
        test: Callable[[], testcases.TestCase],
        server_params: str,
        client_params: str,
    ) -> Tuple[TestResult, float]:
        start_time = datetime.now()
        sim_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_sim_")
        server_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_server_")
        client_log_dir = tempfile.TemporaryDirectory(dir="/tmp", prefix="logs_client_")
        log_file = tempfile.NamedTemporaryFile(dir="/tmp", prefix="output_log_")
        log_handler = logging.FileHandler(log_file.name)
        log_handler.setLevel(logging.DEBUG)

        formatter = LogFileFormatter("%(asctime)s %(message)s")
        log_handler.setFormatter(formatter)
        logging.getLogger().addHandler(log_handler)

        testcase = test(
            sim_log_dir=sim_log_dir,
            client_keylog_file=client_log_dir.name + "/keys.log",
            server_keylog_file=server_log_dir.name + "/keys.log",
        )
        print(
            "Server: "
            + server
            + ". Client: "
            + client
            + ". Running test case: "
            + str(testcase)
        )

        reqs = " ".join([testcase.urlprefix() + p for p in testcase.get_paths()])
        logging.debug("Requests: %s", reqs)
        params = (
            "WAITFORSERVER=server:443 "
            "CERTS=" + testcase.certs_dir() + " "
            "TESTCASE_SERVER=" + testcase.testname(Perspective.SERVER) + " "
            "TESTCASE_CLIENT=" + testcase.testname(Perspective.CLIENT) + " "
            "WWW=" + testcase.www_dir() + " "
            "DOWNLOADS=" + testcase.download_dir() + " "
            "SERVER_LOGS=" + server_log_dir.name + " "
            "CLIENT_LOGS=" + client_log_dir.name + " "
            'SCENARIO="{}" '
            "CLIENT=" + self._implementations[client]["image"] + " "
            "SERVER=" + self._implementations[server]["image"] + " "
            'REQUESTS="' + reqs + '" '
            'VERSION="' + testcases.QUIC_VERSION + '" '
        ).format(testcase.scenario())
        params += " ".join(testcase.additional_envs())

        # Config
        params += (
            'SERVER_PARAMS="'
            + server_params
            + '" CLIENT_PARAMS="'
            + client_params
            + '"'
        )

        containers = "sim client server " + " ".join(testcase.additional_containers())
        cmd = (
            params
            + " docker-compose up --abort-on-container-exit --timeout 1 "
            + containers
        )
        logging.debug("Command: %s", cmd)

        status = TestResult.FAILED
        output = ""
        expired = False
        try:
            r = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=testcase.timeout(),
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        logging.debug("%s", output.decode("utf-8"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", testcase.timeout())
            r = subprocess.run(
                "docker-compose stop " + containers,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            logging.debug("%s", r.stdout.decode("utf-8"))

        # copy the pcaps from the simulator
        self._copy_logs("sim", sim_log_dir)
        self._copy_logs("client", client_log_dir)
        self._copy_logs("server", server_log_dir)

        if not expired:
            lines = output.splitlines()
            if self._is_unsupported(lines):
                status = TestResult.UNSUPPORTED
            elif any("client exited with code 0" in str(line) for line in lines):
                try:
                    status = testcase.check()
                except FileNotFoundError as e:
                    logging.error(f"testcase.check() threw FileNotFoundError: {e}")
                    status = TestResult.FAILED

        # save logs
        logging.getLogger().removeHandler(log_handler)
        log_handler.close()
        if status == TestResult.FAILED or status == TestResult.SUCCEEDED:
            log_dir = self._log_dir + "/" + server + "_" + client + "/" + str(testcase)
            if log_dir_prefix:
                log_dir += "/" + log_dir_prefix
            # shutil.copytree(server_log_dir.name, log_dir + "/server")
            # shutil.copytree(client_log_dir.name, log_dir + "/client")
            # shutil.copytree(sim_log_dir.name, log_dir + "/sim")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            shutil.copyfile(log_file.name, log_dir + "/output.txt")
            if self._save_files and status == TestResult.FAILED:
                shutil.copytree(testcase.www_dir(), log_dir + "/www")
                try:
                    shutil.copytree(testcase.download_dir(), log_dir + "/downloads")
                except Exception as exception:
                    logging.info("Could not copy downloaded files: %s", exception)

        testcase.cleanup()
        server_log_dir.cleanup()
        client_log_dir.cleanup()
        sim_log_dir.cleanup()
        logging.debug(
            "Test: %s took %ss, status: %s",
            str(testcase),
            (datetime.now() - start_time).total_seconds(),
            str(status),
        )

        # measurements also have a value
        if hasattr(testcase, "result"):
            value = testcase.result()
        else:
            value = None

        return status, value

    def _run_measurement(
        self, server: str, client: str, test: Callable[[], testcases.Measurement]
    ) -> MeasurementResult:
        values = []
        for i in range(0, test.repetitions()):
            result, value = self._run_test(server, client, "%d" % (i + 1), test)
            if result != TestResult.SUCCEEDED:
                res = MeasurementResult()
                res.result = result
                res.details = ""
                return res
            values.append(value)

        logging.debug(values)
        res = MeasurementResult()
        res.result = TestResult.SUCCEEDED
        res.details = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(values), statistics.stdev(values), test.unit()
        )
        return res

    def _export_quic_optimization(self, all_results, best_result, default_result):
        columns = ["Command", "Server", "Client"]
        parsed_results = []
        best_goodput = 0
        best_test = None
        for idx, test in enumerate(all_results):
            table = prettytable.PrettyTable(columns)
            table.align = "l"
            for command in test["commands"]:
                table.add_row([command["cmd"], command["server"], command["client"]])
            table_str = table.get_string()
            separator = "-" * len(table_str.splitlines()[0])
            formatted_test = f"Test #{test['counter']}\n\n{table_str}\nGoodput: {test['goodput']} kbps\n{separator}\n\n"

            # Besten Goodput überprüfen
            if test["goodput"] > best_goodput:
                best_goodput = test["goodput"]
                best_test = formatted_test
            parsed_results.append(formatted_test)

        # All results
        with open(self._log_dir + "/all_results.txt", "w") as f:
            f.write("".join(parsed_results))

        # Best result
        with open(self._log_dir + "/best_result.txt", "w") as f:
            test_time = datetime.now() - self._start_time
            text = (
                f"{best_test}Run took: {test_time}\n\n"
                f"Mean with optimized params: {best_result}\n"
                f"Mean with default params: {default_result}"
            )
            f.write(text)

    def _export_opt_test_result(self, commands, goodput, counter, start_time, log_dir):
        test_time = (datetime.now() - start_time).total_seconds()
        table = prettytable.PrettyTable(["Command", "Server", "Client"])
        table.align = "l"
        for command in commands:
            table.add_row([command["cmd"], command["server"], command["client"]])
        table_str = table.get_string()
        output = f"Test #{counter}\n\n{table_str}\n\nRun took: {test_time}s\nGoodput: {goodput} kbps"

        with open(f"{log_dir}/result.txt", "w") as f:
            f.write(output)

    def _get_opt_cmds(self, server, trial):
        commands = []
        server_name = "lsquic" if server == "my-lsquic" else server

        with open(f"./opt/implementations/{server_name}.json", "r") as f:
            config = json.load(f)

        def add_variation(param_cmd, param_info, param_type):
            cmd_info = {"cmd": param_cmd}
            for role in ["server", "client"]:
                if param_info["for"] in [role, "both"]:
                    value = (
                        trial.suggest_categorical(
                            f"{param_cmd}_{role}", param_info["values"]
                        )
                        if param_type == "categorical"
                        else trial.suggest_int(
                            f"{param_cmd}_{role}", *param_info["range"]
                        )
                    )
                    cmd_info[role] = value
            return cmd_info if "server" in cmd_info or "client" in cmd_info else None

        for param_cmd, param_info in config.items():
            cmd_info = add_variation(param_cmd, param_info, param_info["type"])
            if cmd_info:
                commands.append(cmd_info)

        return commands

    def _compare_with_default_conf(
        self,
        server: str,
        client: str,
        test: Callable[[], testcases.Measurement],
        server_cmd,
        client_cmd,
    ):
        # best_server_cmd, best_client_cmd = params_to_cmd_strings(best_params)

        best_test_values = []
        default_test_values = []

        for i in range(5):
            default_result, default_val = self._run_test(
                server,
                client,
                f"default_{i}",
                test,
                "",
                "",
            )

            default_test_values.append(default_val)

        for j in range(5):
            opt_result, opt_val = self._run_test(
                server,
                client,
                f"default_{j}",
                test,
                server_cmd,
                client_cmd,
            )

            best_test_values.append(opt_val)

        best_result = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(best_test_values),
            statistics.stdev(best_test_values),
            test.unit(),
        )

        default_result = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(default_test_values),
            statistics.stdev(default_test_values),
            test.unit(),
        )

        logging.debug("BEST RESULT\n" + best_result + "\n")
        logging.debug("DEFAULT RESULT\n" + default_result + "\n")

        return best_result, default_result

    def _run_quic_optimization(
        self, server: str, client: str, test: Callable[[], testcases.Measurement]
    ) -> MeasurementResult:
        # logging.debug("hallo")
        # self._run_http2_transfer(test)
        values = []
        counter = 0
        output_tables = []

        def generate_command_strings(commands, server, client):
            server_cmd = ""
            client_cmd = ""
            for config in commands:
                if "server" in config:
                    if server in ["lsquic", "my-lsquic"]:
                        server_cmd += f" {config['cmd']}={config['server']}"
                    elif server == "quiche":
                        server_cmd += f" {config['cmd']} {config['server']}"

                if "client" in config:
                    if client in ["lsquic", "my-lsquic"]:
                        client_cmd += f" {config['cmd']}={config['client']}"
                    elif client == "quiche":
                        client_cmd += f" {config['cmd']} {config['client']}"

            return server_cmd.strip(), client_cmd.strip()

        def objective(trial):
            nonlocal counter
            start_time = datetime.now()
            commands = self._get_opt_cmds(server, trial)

            server_cmd, client_cmd = generate_command_strings(commands, server, client)

            result, value = self._run_test(
                server, client, str(counter), test, server_cmd, client_cmd
            )

            if result != TestResult.SUCCEEDED:
                res = MeasurementResult()
                res.result = result
                res.details = ""
                return res

            log_dir = f"{self._log_dir}/{server}_{client}/quic_params/{counter}"
            self._export_opt_test_result(commands, value, counter, start_time, log_dir)

            output_tables.append(
                {"commands": commands, "goodput": value, "counter": counter}
            )

            values.append(value)
            counter += 1
            return value

        def params_to_cmd_strings(best_params):
            server_cmds = ""
            client_cmds = ""

            for key, value in best_params.items():
                cmd, target = key.rsplit(
                    "_", 1
                )  # Trennt den letzten Teil nach dem Unterstrich ab
                if target == "server":
                    server_cmds += f" {cmd} {value}"
                elif target == "client":
                    client_cmds += f" {cmd} {value}"

            return server_cmds.strip(), client_cmds.strip()

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=2)

        best_params = study.best_params
        # best_value = study.best_value

        # Let optimized params compete against default params
        best_server_cmd, best_client_cmd = params_to_cmd_strings(best_params)

        # best_server_cmd = "--cc-algorithm bbr --max-data 12829185 --max-window 28916000 --max-stream-data 829907 --max-stream-window 19856250 --max-streams-bidi 86 --max-streams-uni 112 --initial-cwnd-packets 12"
        # best_client_cmd = "--cc-algorithm bbr --max-data 12469961 --max-window 21366335 --max-stream-data 1339680 --max-stream-window 12553325 --max-streams-bidi 80 --max-streams-uni 81 --initial-cwnd-packets 9"

        # best_server_cmd = "-o cc_algo=1 -o cfcw=40304 -o sfcw=28176 -o init_max_data=13460996 -o max_cfcw=20132659 -o max_sfcw=99181 -o init_max_streams_bidi=94 -o init_max_streams_uni=102"
        # best_client_cmd = "-o cc_algo=2 -o cfcw=94730 -o sfcw=56260 -o init_max_data=12237770 -o max_cfcw=20132659 -o max_sfcw=110821 -o init_max_streams_bidi=107 -o init_max_streams_uni=95"

        best_result, default_result = self._compare_with_default_conf(
            server, client, test, best_server_cmd, best_client_cmd
        )

        self._export_quic_optimization(output_tables, best_result, default_result)
        logging.debug(values)

        res = MeasurementResult()
        res.result = TestResult.SUCCEEDED
        res.details = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(values), statistics.stdev(values), test.unit()
        )
        return res

    def _fetch_file(self, size, unit, bandwidth, delay):
        expired = False

        try:
            r = subprocess.run(
                "docker-compose up -d http2_client",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        logging.debug("%s", output.decode("utf-8"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", 180)
            r = subprocess.run(
                "docker-compose stop http2_client",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            logging.debug("%s", r.stdout.decode("utf-8"))

        subprocess.run(
            "docker exec quic-interop-runner_http2_client_1 tc qdisc add dev eth0 handle 1: ingress",
            shell=True,
        )
        # subprocess.run(
        #     f"docker exec http2_client tc filter add dev eth0 parent 1: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate {bandwidth}mbit burst 10k drop flowid :1"
        # )
        subprocess.run(
            f"docker exec quic-interop-runner_http2_client_1 tc qdisc add dev eth0 root tbf rate {bandwidth}mbit latency {delay}ms burst 10k",
            shell=True,
        )

        curl_command = [
            "docker-compose",
            "exec",
            "-T",
            "http2_client",
            "curl",
            "-o",
            "/dev/null",
            "-s",
            "-w",
            "%{time_total}",
            "--cacert",
            "/certs/cert.pem",
            "https://172.28.1.1/",
        ]

        times = []
        for _ in range(5):
            logging.debug("Curling...")
            result = subprocess.run(curl_command, stdout=subprocess.PIPE, text=True)
            if result.returncode == 0:
                # Konvertieren Sie die Ausgabe zu float und fügen Sie sie der Liste hinzu
                # logging.debug("--------")
                # logging.debug(result.stdout.strip())
                # logging.debug("--------")
                time_s = float(result.stdout.strip())
                time_ms = time_s * 1000
                goodput_bps = size * unit * 8 / time_s
                goodput_kbps = goodput_bps / 1024
                logging.debug(
                    "Transfering %d MB took %d ms. Goodput: %d kbps",
                    size,
                    time_ms,
                    goodput_kbps,
                )
                times.append(goodput_kbps)
            else:
                print(f"Error during curl command: {result.stderr}")

        subprocess.run(
            "docker-compose stop http2_client",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )

        return times

    def _run_http2_transfer(self, test):
        subprocess.run("rm -rf ./http2/certs", shell=True)
        testcases.generate_cert_chain("./http2/certs")

        with open("./opt/config.json", "r") as f:
            config = json.load(f)

        size = int(config["filesize"])
        unit = testcases.KB if config.get("filesize_unit") == "KB" else testcases.MB
        bandwidth = int(config["bandwidth"])
        delay = int(config["delay"])
        # generate random file
        FILESIZE = size * unit
        directory = "http2/www/"
        os.makedirs(directory, exist_ok=True)
        filename = "random_file"
        enc = AES.new(os.urandom(32), AES.MODE_OFB, b"a" * 16)
        file_path = os.path.join(directory, filename)
        with open(file_path, "wb") as f:
            f.write(enc.encrypt(b" " * FILESIZE))

        expired = False

        try:
            r = subprocess.run(
                "docker-compose up -d http2_server",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        logging.debug("%s", output.decode("utf-8"))

        if expired:
            logging.debug("Test failed: took longer than %ds.", 180)
            r = subprocess.run(
                "docker-compose stop http2_server",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            logging.debug("%s", r.stdout.decode("utf-8"))

        subprocess.run(
            "docker exec quic-interop-runner_http2_server_1 tc qdisc add dev eth0 handle 1: ingress",
            shell=True,
        )
        # subprocess.run(
        #     f"docker exec http2_server tc filter add dev eth0 parent 1: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate 50mbit burst 10k drop flowid :1"
        # )
        subprocess.run(
            f"docker exec quic-interop-runner_http2_server_1 tc qdisc add dev eth0 root tbf rate {bandwidth}mbit latency {delay}ms burst 10k",
            shell=True,
        )

        # Führe den fetch_file Befehl 5 Mal aus und speichere die Zeiten
        times = self._fetch_file(size, unit, bandwidth, delay)

        subprocess.run(
            "docker-compose stop http2_server",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )

        logging.debug("AND HERE COME... THE TIMES\n")
        logging.debug(times)
        logging.debug("-------------------")

        result = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(times), statistics.stdev(times), test.unit()
        )

        logging.debug(result)

    def run(self):
        """run the interop test suite and output the table"""

        nr_failed = 0
        for server in self._servers:
            for client in self._clients:
                logging.debug(
                    "Running with server %s (%s) and client %s (%s)",
                    server,
                    self._implementations[server]["image"],
                    client,
                    self._implementations[client]["image"],
                )
                # if not (
                #     self._check_impl_is_compliant(server)
                #     and self._check_impl_is_compliant(client)
                # ):
                #     logging.info("Not compliant, skipping")
                #     continue

                # run the test cases
                for testcase in self._tests:
                    status = self._run_testcase(server, client, testcase)
                    self.test_results[server][client][testcase] = status
                    if status == TestResult.FAILED:
                        nr_failed += 1

                # run the measurements
                for measurement in self._measurements:
                    if measurement.abbreviation() == "QO":
                        res = self._run_quic_optimization(server, client, measurement)
                        # self._run_http2_transfer()
                    else:
                        res = self._run_measurement(server, client, measurement)
                    self.measurement_results[server][client][measurement] = res

        self._print_results()
        self._export_results()
        return nr_failed
