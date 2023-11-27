import colorsys
import logging
import os
import re
import shutil
import csv

import matplotlib.colors as mc
import matplotlib.pyplot as plt
import numpy as np
from numpy.polynomial.polynomial import Polynomial


def parse_goodput_from_file(filename):
    """Extrahiert Goodput-Werte aus einer Datei und gibt sie als Liste von Floats zurück."""
    with open(filename, "r") as file:
        content = file.read()
        goodput_matches = re.findall(r"Goodput: ([\d.]+) kbps", content)
        return [float(value) for value in goodput_matches]


def plot_goodput_over_time(goodput_values, label, color, filename):
    """Erstellt ein Liniendiagramm des Goodputs über die Zeit."""
    plt.figure(figsize=(10, 4))
    plot_goodput_trendline(goodput_values, label, color)
    plt.title(f"Goodput pro Testlauf mit Trendlinie ({label})")
    plt.xlabel("Testlauf")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_boxplot(goodput_values, label, filename):
    """Erstellt einen Box-Plot für die Goodput-Werte."""
    plt.figure(figsize=(10, 6))
    plt.boxplot(goodput_values, vert=True, patch_artist=True)
    plt.title(f"Box-Plot des Goodputs ({label})")
    plt.ylabel("Goodput (kbps)")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_histogram(goodput_values, label, filename, bins=50):
    """Erstellt ein Histogramm für die Goodput-Werte."""
    plt.figure(figsize=(10, 6))
    plt.hist(goodput_values, bins=bins, color="blue", alpha=0.7)
    plt.title(f"Histogramm des Goodputs ({label})")
    plt.xlabel("Goodput (kbps)")
    plt.ylabel("Häufigkeit")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_combined_goodput(goodput_data, filename):
    """Erstellt ein kombiniertes Liniendiagramm des Goodputs für alle Implementierungen."""
    plt.figure(figsize=(10, 4))
    for label, (goodput_values, color) in goodput_data.items():
        plot_goodput_trendline(goodput_values, label, color, plot_combined=True)
    plt.title("Goodput pro Testlauf mit Trendlinie (kombiniert)")
    plt.xlabel("Testlauf")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_moving_average(values, label, color, window_size=50):
    """Berechnet und plottet den gleitenden Durchschnitt über ein definiertes Fenster."""
    cumsum = np.cumsum(np.insert(values, 0, 0))
    ma = (cumsum[window_size:] - cumsum[:-window_size]) / float(window_size)
    x_ma = np.arange(window_size, window_size + len(ma))
    plt.plot(
        x_ma,
        ma,
        linestyle="--",
        linewidth=1.5,
        color=color,
        label=f"Gleitender Durchschnitt {label}",
    )


def plot_poly_fit(x, y, trendline_color, label):
    """Berechnet Polynom 2. Grades als Trendlinie."""
    p = Polynomial.fit(x, y, 2)
    x_new = np.linspace(x.min(), x.max(), 100)
    y_new = p(x_new)
    plt.plot(
        x_new,
        y_new,
        linestyle="--",
        linewidth=1.5,
        color=trendline_color,
        label=f"Trendlinie {label}",
    )


def plot_goodput_trendline(
    goodput_values, label, color, plot_combined=False, trendline="ma"
):
    """Visualisiert Goodput-Werte in einem linearen Diagramm mit optionaler Trendlinie."""
    x = np.array(range(1, len(goodput_values) + 1))
    y = np.array(goodput_values)
    plt.plot(
        x, y, "-o" if not plot_combined else "o", label=f"Goodput {label}", color=color
    )

    trendline_color = adjust_lightness(color, 1.5)

    if trendline == "ma":
        plot_moving_average(goodput_values, label, trendline_color, window_size=50)
    elif trendline == "poly":
        plot_poly_fit(x, y, trendline_color, label)


def generate_plots(files):
    """Generiert Plots für jede Implementierung."""
    goodput_data = {}

    # Goodput-Werte einmal auslesen und in einem Dictionary speichern
    for label, (filename, color) in files.items():
        goodput_values = parse_goodput_from_file(filename)
        goodput_data[label] = (goodput_values, color)

    # Einzelne Diagramme für jede Implementierung
    for label, (goodput_values, color) in goodput_data.items():
        plot_goodput_over_time(
            goodput_values, label, color, f"analytics/goodput_{label}.svg".lower()
        )
        plot_goodput_boxplot(
            goodput_values, label, f"analytics/goodput_boxplot_{label}.svg".lower()
        )
        plot_goodput_histogram(
            goodput_values, label, f"analytics/goodput_histogram_{label}.svg".lower()
        )

    # Kombiniertes Goodput Diagramm
    plot_combined_goodput(goodput_data, "analytics/goodput_combined.svg")


def print_optimized_commands(file_path, connector=" "):
    with open(file_path, "r") as f:
        lines = f.readlines()

    server_cmds = ""
    client_cmds = ""

    for line in lines:
        line = line.strip()
        if line.startswith("|") and not line.startswith("| Command"):
            parts = line.split("|")
            command = parts[1].strip()
            server_value = parts[2].strip()
            client_value = parts[3].strip()

            if server_value:
                server_cmds += f" {command}{connector}{server_value}"
            if client_value:
                client_cmds += f" {command}{connector}{client_value}"

    print("\nServer:")
    print(server_cmds.strip())
    print("\nClient:")
    print(client_cmds.strip())


def create_csv_from_test_results(input_file_path, output_csv_path, connector=" "):
    """
    Reads the test results from the original file and creates a CSV file with the specified format.
    """
    results = []

    with open(input_file_path, "r") as f:
        lines = f.readlines()

    current_test = {}
    server_cmds = {}
    client_cmds = {}

    for line in lines:
        line = line.strip()

        if line.startswith("Test #"):
            # Process the previous test result before starting a new one
            if current_test:
                for key in server_cmds:
                    current_test[key + " (Server)"] = server_cmds[key]
                for key in client_cmds:
                    current_test[key + " (Client)"] = client_cmds[key]
                results.append(current_test)

            # Reset for new test
            current_test = {"Test Number": int(line.split("#")[1])}
            server_cmds = {}
            client_cmds = {}

        elif line.startswith("| ") and not line.startswith("| Command"):
            parts = line.split("|")
            command = parts[1].strip()
            server_value = parts[2].strip()
            client_value = parts[3].strip()

            if server_value:
                server_cmds[command] = server_value
            if client_value:
                client_cmds[command] = client_value

        elif line.startswith("Goodput:"):
            goodput_value = float(line.split(":")[1].strip().split(" ")[0])
            current_test["Goodput (kbps)"] = goodput_value

    # Add the last test to results
    if current_test:
        for key in server_cmds:
            current_test[key + " (Server)"] = server_cmds[key]
        for key in client_cmds:
            current_test[key + " (Client)"] = client_cmds[key]
        results.append(current_test)

    # Determining the columns for the CSV
    columns = set()
    for test in results:
        for key in test:
            columns.add(key)
    columns = list(sorted(columns))

    # Writing to CSV
    with open(output_csv_path, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columns)
        writer.writeheader()
        for test in results:
            writer.writerow(test)


def adjust_lightness(color, factor):
    """Passt die Helligkeit einer Farbe an."""

    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, factor * c[1])), c[2])


def find_best_goodput():
    best_goodput = 0
    best_file_path = ""

    # Durchlaufe alle Unterordner im angegebenen Ordner
    for subdir, _, _ in os.walk("/"):
        file_path = os.path.join(subdir, "result.txt")

        # Überprüfe, ob die result.txt-Datei existiert
        if os.path.isfile(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()

            # Suche nach der Goodput-Zeile
            for line in lines:
                if "Goodput:" in line:
                    # Extrahiere die Goodput-Zahl
                    _, goodput = line.split("Goodput:")
                    goodput = float(goodput.split("kbps")[0].strip())

                    # Aktualisiere best_goodput und best_file_path wenn nötig
                    if goodput > best_goodput:
                        best_goodput = goodput
                        best_file_path = file_path

    return best_file_path, best_goodput


def main():
    files = {
        "LSQUIC": ("analytics/lsquic_all_results.txt", "royalblue"),
        "Quiche": ("analytics/quiche_all_results.txt", "darkorange"),
    }
    generate_plots(files)

    # create_csv_from_test_results(
    #     "analytics/lsquic_all_results.txt", "analytics/lsquic_all_results.csv", "="
    # )
    # path_best_result = "./quiche_best_result.txt"
    # print_optimized_commands(path_best_result, "=")
    # path, goodput = find_best_goodput()
    # print(path)
    # print(goodput)


if __name__ == "__main__":
    main()
