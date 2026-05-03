import ttkbootstrap as tb
from ui import App, HAS_DND

if HAS_DND:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
    tb.Style(theme="darkly")
else:
    root = tb.Window(title="PLN Billing Analyzer", themename="darkly")

root.title("PLN Billing Analyzer")
app = App(root)
root.mainloop()
