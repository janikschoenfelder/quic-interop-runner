import colorsys
import csv
import logging
import os
import re
import shutil

import matplotlib.colors as mc
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from numpy.polynomial.polynomial import Polynomial
from sklearn.preprocessing import LabelEncoder


def parse_goodput_from_file(filename):
    with open(filename, "r") as file:
        content = file.read()
        goodput_matches = re.findall(r"Goodput: ([\d.]+) kbps", content)
        return [float(value) for value in goodput_matches]


# Liniendiagramm
def plot_goodput_over_time(goodput_values, label, color, filename):
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


# Kombiniertes liniendiagramm
def plot_combined_goodput(goodput_data, filename):
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


def plot_goodput_boxplot_combined(goodput_data, filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    goodputs = [data[0] for data in goodput_data.values()]
    labels = list(goodput_data.keys())
    ax.boxplot(goodputs, labels=labels, patch_artist=True)
    # ax.set_title("Kombinierter Box-Plot des Goodputs")
    ax.set_ylabel("Goodput (kbps)")
    ax.grid(True, which="both", linestyle="--", linewidth=0.5)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_boxplot(goodput_values, label, filename):
    plt.figure(figsize=(10, 6))
    plt.boxplot(goodput_values, vert=True, patch_artist=True)
    plt.title(f"Box-Plot des Goodputs ({label})")
    plt.ylabel("Goodput (kbps)")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_histogram(goodput_values, label, filename, bins=50):
    plt.figure(figsize=(10, 6))
    plt.hist(goodput_values, bins=bins, color="blue", alpha=0.7)
    plt.title(f"Histogramm des Goodputs ({label})")
    plt.xlabel("Goodput (kbps)")
    plt.ylabel("Häufigkeit")
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_moving_average(values, label, color, window_size=1000):
    cumsum = np.cumsum(np.insert(values, 0, 0))
    ma = (cumsum[window_size:] - cumsum[:-window_size]) / float(window_size)
    x_ma = np.arange(window_size, window_size + len(ma))
    plt.plot(
        x_ma,
        ma,
        linestyle="-",
        linewidth=1.5,
        color="black",
        label=f"Gleitender Durchschnitt {label}",
    )


# Polynom 2. Grades als Trendlinie
def plot_poly_fit(x, y, trendline_color, label):
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


# Lineares Diagramm mit Trendlinie
def plot_goodput_trendline(
    goodput_values, label, color, plot_combined=False, trendline="ma"
):
    x = np.array(range(1, len(goodput_values) + 1))
    y = np.array(goodput_values)

    plt.scatter(x, y, label=f"Goodput {label}", color=color, s=10)

    trendline_color = adjust_lightness(color, 1.5)

    # if trendline == "ma":
    #     plot_moving_average(goodput_values, label, trendline_color, window_size=50)
    # elif trendline == "poly":
    #     plot_poly_fit(x, y, trendline_color, label)


def generate_plots(files, concat=False):
    goodput_data = {}

    for label, (filename, color) in files.items():
        goodput_values = parse_goodput_from_file(filename)
        goodput_data[label] = (goodput_values, color)

        # goodput trend
        plot_goodput_over_time(
            goodput_values, label, color, f"analytics/goodput_{label}.svg".lower()
        )

        # histo
        plot_goodput_histogram(
            goodput_values, label, f"analytics/goodput_histogram_{label}.svg".lower()
        )

    if concat:
        # combined boxplot
        plot_goodput_boxplot_combined(
            goodput_data, "analytics/goodput_boxplot_combined.svg"
        )
    else:
        # separate boxplot
        for label, (goodput_values, _) in goodput_data.items():
            plot_goodput_boxplot(
                goodput_values, label, f"analytics/goodput_boxplot_{label}.svg".lower()
            )

    # combined goodput trend
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
    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, factor * c[1])), c[2])


def find_best_goodput():
    best_goodput = 0
    best_file_path = ""

    for subdir, _, _ in os.walk("/"):
        file_path = os.path.join(subdir, "result.txt")

        if os.path.isfile(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()

            for line in lines:
                if "Goodput:" in line:
                    _, goodput = line.split("Goodput:")
                    goodput = float(goodput.split("kbps")[0].strip())

                    if goodput > best_goodput:
                        best_goodput = goodput
                        best_file_path = file_path

    return best_file_path, best_goodput


def plot_goodput_over_time_seaborn(goodput_values, label, color, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 4))
    plt.scatter(
        range(len(goodput_values)), goodput_values, label=label, color=color, s=10
    )
    plt.title(f"Goodput über die Zeit ({label})")
    plt.xlabel("Testnummer")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_over_time_seaborn_smooth(goodput_values, label, color, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 4))
    plt.scatter(
        range(len(goodput_values)),
        goodput_values,
        label=f"{label} Datenpunkte",
        color=adjust_lightness(color, 1.2),
        s=5,
        alpha=0.3,
    )
    smooth_data = np.convolve(goodput_values, np.ones(50) / 50, mode="valid")
    plt.plot(smooth_data, label=f"{label} Gleitender Durchschnitt", color=color)
    # plt.title(f"Goodput über die Zeit ({label})")
    plt.xlabel("Testnummer")
    plt.ylabel("Goodput (kbps)")
    plt.legend(loc="lower left")
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_histogram_seaborn(goodput_values, label, color, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 4))
    sns.histplot(goodput_values, color=color, kde=True, label=label)
    # plt.title(f"Goodput Histogramm ({label})")
    plt.xlabel("Goodput (kbps)")
    plt.ylabel("Häufigkeit")
    plt.xlim([min(goodput_values), max(goodput_values)])
    plt.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_boxplot_seaborn(goodput_values, label, color, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 4))
    sns.boxplot(data=goodput_values, color=color)
    # plt.title(f"Goodput Boxplot ({label})")
    plt.xlabel("Implementierung")
    plt.ylabel("Goodput (kbps)")
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_goodput_boxplot_combined_seaborn(goodput_data, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 8))
    data, colors = zip(
        *[(values, color) for label, (values, color) in goodput_data.items()]
    )
    colors = [adjust_lightness(color, 1.4) for color in colors]
    sns.boxplot(data=data, palette=colors)
    # plt.title("Kombinierter Goodput Boxplot")
    plt.xlabel("Implementierung")
    plt.ylabel("Goodput (kbps)")
    plt.xticks(range(len(goodput_data)), goodput_data.keys())
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_combined_goodput_seaborn(goodput_data, filename):
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 4))
    for label, (goodput_values, color) in goodput_data.items():
        plt.plot(range(len(goodput_values)), goodput_values, label=label, color=color)
    # plt.title("Kombinierter Goodput-Verlauf")
    plt.xlabel("Testnummer")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()


def plot_heatmaps_for_csv(label):
    data = pd.read_csv(f"{label}_all_results.csv")
    data = data.drop(columns=["Test Number"])

    # converts categorical to numerical
    label_encoder = LabelEncoder()
    for column in data.columns:
        if data[column].dtype == "object":
            data[column] = label_encoder.fit_transform(data[column])

    data = data.loc[:, data.std() > 0]

    correlation_with_goodput = data.corrwith(data["Goodput (kbps)"]).drop(
        "Goodput (kbps)"
    )

    plt.figure(figsize=(8, 6))
    sns.heatmap(
        correlation_with_goodput.to_frame(),
        annot=True,
        cmap="coolwarm",
        vmin=-1,
        vmax=1,
    )
    plt.title("Korrelation mit Goodput")
    plt.savefig(f"{label}_correlation_with_goodput_heatmap.png")
    plt.close()


def plot_pair_plots_for_csv(label):
    data = pd.read_csv(f"{label}_all_results.csv")
    data = data.drop(columns=["Test Number"])

    columns_for_pair_plot = [col for col in data.columns if col != "Goodput (kbps)"]
    columns_for_pair_plot.append("Goodput (kbps)")

    sns.pairplot(data[columns_for_pair_plot])
    plt.suptitle("Pair Plot mit Goodput", y=1.02)

    plt.savefig(f"analytics/pair/{label}_pairplot.svg")
    plt.close()


def plot_individual_relationship_with_goodput(label):
    data = pd.read_csv(f"{label}_all_results.csv")
    variables = data.drop(columns=["Test Number", "Goodput (kbps)"]).columns

    for var in variables:
        plt.figure(figsize=(8, 6))
        sns.scatterplot(x=var, y="Goodput (kbps)", data=data)
        plt.title(f"Beziehung zwischen {var} und Goodput")
        plt.xlabel(var)
        plt.ylabel("Goodput (kbps)")
        plt.savefig(f"analytics/pair/{label}_{var}_goodput_relation.svg")
        plt.close()


def plot_kde(label):
    data = pd.read_csv(f"{label}_all_results.csv")
    numeric_data = data.select_dtypes(include=["float64", "int64"])
    numeric_data = numeric_data.drop(columns=["Test Number"])

    for column in numeric_data.columns:
        # kde needs std
        if numeric_data[column].std() > 0:
            plt.figure(figsize=(8, 6))
            sns.kdeplot(
                data=numeric_data, x=column, y="Goodput (kbps)", warn_singular=False
            )
            plt.title(f"KDE von {column} und Goodput")
            plt.savefig(f"analytics/kde/{label}_kde_{column}_vs_goodput.svg")
            plt.close()
        else:
            print(f"Warnung: Keine ausreichende Varianz in {column} für KDE.")


def plot_jointplots(label):
    data = pd.read_csv(f"{label}_all_results.csv")
    variables = data.drop(columns=["Test Number", "Goodput (kbps)"]).columns

    for var in variables:
        sns.jointplot(x=var, y="Goodput (kbps)", data=data, kind="scatter")
        plt.title(f"Jointplot von {var} und Goodput", pad=70)
        plt.savefig(f"analytics/joint/{label}_jointplot_{var}_vs_goodput.svg")
        plt.close()


def generate_plots_seaborn(files, testrun, concat=False):
    goodput_data = {}

    # gather goodput values and save in dict
    for label, (filename, color) in files.items():
        goodput_values = parse_goodput_from_file(filename)
        goodput_data[label] = (goodput_values, color)

        plot_goodput_over_time_seaborn(
            goodput_values,
            label,
            color,
            f"analytics/{testrun}/goodput_{label}.svg".lower(),
        )
        plot_goodput_over_time_seaborn_smooth(
            goodput_values,
            label,
            color,
            f"analytics/{testrun}/goodput_smooth_{label}.svg".lower(),
        )
        plot_goodput_histogram_seaborn(
            goodput_values,
            label,
            color,
            f"analytics/{testrun}/goodput_histogram_{label}.svg".lower(),
        )
        # plot_heatmaps_for_csv(label)
        # plot_pair_plots_for_csv(label)
        # plot_individual_relationship_with_goodput(label)
        # plot_kde(label)
        # plot_jointplots(label)

    if concat:
        # combined boxplots
        plot_goodput_boxplot_combined_seaborn(
            goodput_data, f"analytics/{testrun}/goodput_boxplot_combined.svg"
        )
    else:
        # separate boxplots
        for label, (goodput_values, color) in goodput_data.items():
            plot_goodput_boxplot_seaborn(
                goodput_values,
                label,
                color,
                f"analytics/{testrun}/goodput_boxplot_{label}.svg".lower(),
            )

    # combined scatter
    plot_combined_goodput_seaborn(
        goodput_data, f"analytics/{testrun}/goodput_combined.svg"
    )


def main():
    testrun = 2500
    files = {
        "LSQUIC": (f"analytics/results/lsquic_all_results_{testrun}.txt", "royalblue"),
        "Quiche": (f"analytics/results/quiche_all_results_{testrun}.txt", "darkorange"),
    }
    # generate_plots(files, True)
    generate_plots_seaborn(files, testrun, True)

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
