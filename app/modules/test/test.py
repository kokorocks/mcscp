import __main__
print("Hello, World")

#from tkinter import messagebox
#
#messagebox.showinfo("Hello", "Hello, World!")

if hasattr(__main__, "app"):
    app = __main__.app
    print(f'even more nestedm test.py file found: {app}')
else:
    print("no")