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

opt_params = {
    "quiche": {
        "--cc-algorithm": {
            "values": ["bbr", "bbr2", "cubic", "reno"],
            "type": "categorical",
            "for": "both",
            "default": "cubic",
        },
        "--max-data": {
            "default": 10000000,
            "type": "integer",
            "range": [10000000, 16 * 1024 * 1024],
            "for": "both",
        },
        "--max-window": {
            "default": 25165824,
            "type": "integer",
            "range": [25165824 * 0.8, 25165824 * 1.2],
            "for": "both",
        },
        "--max-stream-data": {
            "default": 1000000,
            "type": "integer",
            "range": [1000000 * 0.7, 2000000],
            "for": "both",
        },
        "--max-stream-window": {
            "default": 16777216,
            "type": "integer",
            "range": [16777216 * 0.7, 16777216 * 1.3],
            "for": "both",
        },
        "--max-streams-bidi": {
            "default": 100,
            "type": "integer",
            "range": [100 * 0.8, 100 * 1.2],
            "for": "both",
        },
        "--max-streams-uni": {
            "default": 100,
            "type": "integer",
            "range": [100 * 0.8, 100 * 1.2],
            "for": "both",
        },
        "--initial-cwnd-packets": {
            "default": 10,
            "type": "integer",
            "range": [10 * 0.8, 10 * 1.2],
            "for": "both",
        },
    },
    "lsquic": {
        "-o cc_algo": {
            "values": [
                1,
                2,
                3,
            ],  # 0: use default (adaptive), 1: cubic, 2: bbr1, 3: adaptive
            "type": "categorical",
            "for": "both",
            "default": 3,
        },
        "-o cfcw": {
            "default": 16384,
            "type": "integer",
            "range": [16384, 16384 * 2 * 2 * 2],
            "for": "both",
        },
        "-o sfcw": {
            "default": 16384,
            "type": "integer",
            "range": [16384, 16384 * 2 * 2 * 2],
            "for": "both",
        },
        "-o init_max_data": {
            "default": 10000000,
            "type": "integer",
            "range": [10000000, 10000000 * 1.6],
            "for": "both",
        },
        "-o max_cfcw": {
            "default": 25165824,
            "type": "integer",
            "range": [25165824 * 0.8, 25165824 * 0.8],
            "for": "both",
        },
        "-o max_sfcw": {
            "default": 16777216,
            "type": "integer",
            "range": [16384, 16384 * 2 * 2 * 2],
            "for": "both",
        },
        "-o init_max_streams_bidi": {
            "default": 100,
            "type": "integer",
            "range": [100 * 0.8, 100 * 1.2],
            "for": "both",
        },
        "-o init_max_streams_uni": {
            "default": 100,
            "type": "integer",
            "range": [100 * 0.8, 100 * 1.2],
            "for": "both",
        },
    },
}


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
    _parameters = {}

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
        parameters=opt_params,
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
        self._parameters = parameters
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
        logging.debug("Test took %ss", (datetime.now() - start_time).total_seconds())

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

    def _export_quic_optimization(self, all_results):
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
            f.write(best_test + f"Run took: {test_time}")

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

        # iterate over config dictionary
        server_name = "lsquic" if server == "my-lsquic" else server
        for param_cmd, param_info in self._parameters[server_name].items():
            # add flag
            cmd_info = {"cmd": param_cmd}

            # categorical variation
            if param_info["type"] == "categorical":
                # server part
                if param_info["for"] in ["server", "both"]:
                    # generate variation
                    option_server = trial.suggest_categorical(
                        f"{param_cmd}_server", param_info["values"]
                    )

                    # add command value
                    cmd_info["server"] = option_server

                # client part
                if param_info["for"] in ["client", "both"]:
                    # generate variation
                    option_client = trial.suggest_categorical(
                        f"{param_cmd}_client", param_info["values"]
                    )

                    # add command value
                    cmd_info["client"] = option_client

            # integer variation
            if param_info["type"] == "integer":
                low, high = param_info["range"]

                # server part
                if param_info["for"] in ["server", "both"]:
                    # generate variation
                    value_server = trial.suggest_int(f"{param_cmd}_server", low, high)

                    # add command value
                    cmd_info["server"] = value_server

                # client part
                if param_info["for"] in ["client", "both"]:
                    # generate variation
                    value_client = trial.suggest_int(f"{param_cmd}_client", low, high)

                    # add command value
                    cmd_info["client"] = value_client

            # add command to list of all commands only if it has server or client values
            if "server" or "client" in cmd_info:
                commands.append(cmd_info)

        return commands

    def _run_quic_optimization(
        self, server: str, client: str, test: Callable[[], testcases.Measurement]
    ) -> MeasurementResult:
        values = []
        counter = 0
        output_tables = []

        # objective for optuna
        def objective(trial):
            start_time = datetime.now()
            nonlocal counter

            commands = self._get_opt_cmds(server, trial)

            # join variations together to one separate server & client command respectively
            server_cmd = ""
            client_cmd = ""
            for config in commands:
                # add only if present
                if "server" in config:
                    if server == "lsquic" or server == "my-lsquic":
                        server_cmd += f" {config['cmd']}={config['server']}"
                    elif server == "quiche":
                        server_cmd += f" {config['cmd']} {config['server']}"

                # add only if present
                if "client" in config:
                    if client == "lsquic" or client == "my-lsquic":
                        client_cmd += f" {config['cmd']}={config['client']}"
                    elif client == "quiche":
                        client_cmd += f" {config['cmd']} {config['client']}"

            # run the test
            result, value = self._run_test(
                server,
                client,
                f"{counter}",
                test,
                server_cmd.strip(),
                client_cmd.strip(),
            )

            if result != TestResult.SUCCEEDED:
                res = MeasurementResult()
                res.result = result
                res.details = ""
                return res

            log_dir = (
                self._log_dir
                + "/"
                + server
                + "_"
                + client
                + "/quic_params/"
                + str(counter)
            )

            # export test
            self._export_opt_test_result(commands, value, counter, start_time, log_dir)

            counter += 1

            # add result to all_tests output
            output_tables.append(
                {"commands": commands, "goodput": value, "counter": counter}
            )

            values.append(value)

            return value

        # optimize
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=5)

        best_params = study.best_params
        best_value = study.best_value

        # export results
        self._export_quic_optimization(output_tables)

        logging.debug(values)

        res = MeasurementResult()
        res.result = TestResult.SUCCEEDED
        # res.details = "Best test achieved: {:.0f} {}. All tests statistics: {:.0f} (± {:.0f}) {}".format(
        #     best_value,
        #     test.unit(),
        #     statistics.mean(values),
        #     statistics.stdev(values),
        #     test.unit(),
        # )
        res.details = "{:.0f} (± {:.0f}) {}".format(
            statistics.mean(values), statistics.stdev(values), test.unit()
        )
        return res

    def _run_http2_transfer(self):
        # generate ssl certs
        testcases.generate_cert_chain("http2_certs")

        # generate random file
        FILESIZE = 10 * testcases.MB
        filename = "random_file"
        enc = AES.new(os.urandom(32), AES.MODE_OFB, b"a" * 16)
        f = open("http2/" + filename, "wb")
        f.write(enc.encrypt(b" " * FILESIZE))
        f.close()

        cmd = "docker-compose up -d apache"

        try:
            r = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
            )
            output = r.stdout
        except subprocess.TimeoutExpired as ex:
            output = ex.stdout
            expired = True

        fetch_cmd = "curl -k --http2 https://localhost"

        subprocess.run

        # logging.debug("%s", output.decode("utf-8"))

        # if expired:
        #     logging.debug("Test failed: took longer than %ds.", 180)
        #     r = subprocess.run(
        #         "docker-compose stop apache",
        #         shell=True,
        #         stdout=subprocess.PIPE,
        #         stderr=subprocess.STDOUT,
        #         timeout=60,
        #     )
        #     logging.debug("%s", r.stdout.decode("utf-8"))

        try:
            r = subprocess.run(
                fetch_cmd,
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
                if not (
                    self._check_impl_is_compliant(server)
                    and self._check_impl_is_compliant(client)
                ):
                    logging.info("Not compliant, skipping")
                    continue

                # run the test cases
                for testcase in self._tests:
                    status = self._run_testcase(server, client, testcase)
                    self.test_results[server][client][testcase] = status
                    if status == TestResult.FAILED:
                        nr_failed += 1

                # run the measurements
                for measurement in self._measurements:
                    if measurement.abbreviation() == "QP":
                        res = self._run_quic_optimization(server, client, measurement)
                        # self._run_http2_transfer()
                    else:
                        res = self._run_measurement(server, client, measurement)
                    self.measurement_results[server][client][measurement] = res

        self._print_results()
        self._export_results()
        return nr_failed
