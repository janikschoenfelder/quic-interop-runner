import colorsys
import re

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


def adjust_lightness(color, factor):
    """Passt die Helligkeit einer Farbe an."""

    try:
        c = mc.cnames[color]
    except:
        c = color
    c = colorsys.rgb_to_hls(*mc.to_rgb(c))
    return colorsys.hls_to_rgb(c[0], max(0, min(1, factor * c[1])), c[2])


def visualize_goodput(goodput_values, label, color, plot_combined=False):
    """Visualisiert Goodput-Werte in einem linearen Diagramm mit Trendlinie."""
    x = np.array(range(1, len(goodput_values) + 1))
    y = np.array(goodput_values)
    if plot_combined:
        plt.plot(x, y, "o", label=f"Goodput {label}", color=color)
    else:
        plt.plot(x, y, "-o", label=f"Goodput {label}", color=color)

    # Polynom 2. Grades für Trendlinie
    trend_color = adjust_lightness(color, 1.5)
    p = Polynomial.fit(x, y, 2)
    x_new = np.linspace(x.min(), x.max(), 100)
    y_new = p(x_new)
    plt.plot(
        x_new,
        y_new,
        label=f"Trendlinie {label} (Polynom 2. Grades)",
        linestyle="--",
        linewidth=1.5,
        color=trend_color,
    )


def plot_goodput_for_file(filename, label, color):
    plt.figure(figsize=(10, 4))
    goodput_values = parse_goodput_from_file(filename)
    visualize_goodput(goodput_values, label, color)
    plt.title(f"Goodput pro Testlauf mit Trendlinie ({label})")
    plt.xlabel("Testlauf")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig(f"{label}_goodput_diagram.svg")
    plt.show()


def main():
    files = {
        "LSQUIC": ("all_results_lsquic.txt", "royalblue"),
        "Quiche": ("all_results_quiche.txt", "darkorange"),
    }

    # Einzelne Diagramme für jede Datei
    for label, (filename, color) in files.items():
        plot_goodput_for_file(filename, label, color)

    # Kombiniertes Diagramm
    plt.figure(figsize=(10, 4))
    for label, (filename, color) in files.items():
        goodput_values = parse_goodput_from_file(filename)
        visualize_goodput(goodput_values, label, color, plot_combined=True)

    plt.title("Goodput pro Testlauf mit Trendlinie (kombiniert)")
    plt.xlabel("Testlauf")
    plt.ylabel("Goodput (kbps)")
    plt.legend()
    plt.grid(True, which="both", linestyle="--", linewidth=0.5)
    plt.tight_layout()
    plt.savefig("all_data_goodput_diagram.svg")
    plt.show()


if __name__ == "__main__":
    main()
