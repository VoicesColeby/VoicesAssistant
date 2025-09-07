# main_gui.py
import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess
import threading
import sys
import os

class VoicesAutomationApp:
    def __init__(self, master):
        self.master = master
        master.title("Voices.com Automation Tool")
        master.geometry("800x600")

        self.selected_action = None
        self.input_fields = {}

        self.create_widgets()

    def create_widgets(self):
        # Action Buttons Frame
        action_frame = tk.Frame(self.master, pady=10)
        action_frame.pack()

        self.invite_button = tk.Button(action_frame, text="Invite to Job", width=20, command=lambda: self.show_input_fields("invite"))
        self.invite_button.pack(side=tk.LEFT, padx=10)
        
        self.favorites_button = tk.Button(action_frame, text="Add to Favorites", width=20, command=lambda: self.show_input_fields("favorites"))
        self.favorites_button.pack(side=tk.LEFT, padx=10)

        self.message_button = tk.Button(action_frame, text="Message Talent", width=20, command=lambda: self.show_input_fields("message"))
        self.message_button.pack(side=tk.LEFT, padx=10)

        # Input Fields Frame
        self.input_frame = tk.Frame(self.master, padx=10, pady=10)
        self.input_frame.pack(fill=tk.X)

        # Run Button
        self.run_button = tk.Button(self.master, text="Run Automation", command=self.run_automation)
        self.run_button.pack(pady=10)

        # Console Output
        self.console_frame = tk.LabelFrame(self.master, text="Console Output", padx=5, pady=5)
        self.console_frame.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)
        self.console_text = scrolledtext.ScrolledText(self.console_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.console_text.pack(fill=tk.BOTH, expand=True)

    def show_input_fields(self, action):
        # Clear previous fields
        for widget in self.input_frame.winfo_children():
            widget.destroy()
        
        self.input_fields = {}
        self.selected_action = action

        # Create new fields based on the selected action
        if action == "invite":
            self.create_entry("Start URL:", "start_url")
            self.create_entry("Job #:", "job_query")
        elif action == "favorites":
            self.create_entry("Start URL:", "start_url")
            self.create_entry("Favorite List Name:", "favorite_list_name")
        elif action == "message":
            self.create_entry("Start URL:", "start_url")
            self.create_entry("Message:", "message", is_textarea=True)
            self.create_entry("Job # (for validation):", "job_query", optional=True)

    def create_entry(self, label_text, var_name, is_textarea=False, optional=False):
        row_frame = tk.Frame(self.input_frame)
        row_frame.pack(fill=tk.X, pady=2)
        
        label = tk.Label(row_frame, text=label_text, width=20, anchor="w")
        label.pack(side=tk.LEFT, padx=5)

        if is_textarea:
            text_widget = scrolledtext.ScrolledText(row_frame, height=5, width=50)
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            self.input_fields[var_name] = text_widget
        else:
            entry = tk.Entry(row_frame, width=50)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            self.input_fields[var_name] = entry
            
        if optional:
            optional_label = tk.Label(row_frame, text="(Optional)", font=("Arial", 8), fg="gray")
            optional_label.pack(side=tk.LEFT, padx=5)

    def run_automation(self):
        if not self.selected_action:
            messagebox.showerror("Error", "Please select an action first.")
            return

        # Clear console and set to writing mode
        self.console_text.config(state=tk.NORMAL)
        self.console_text.delete(1.0, tk.END)
        self.console_text.config(state=tk.DISABLED)

        # Start the automation in a new thread to keep the GUI responsive
        threading.Thread(target=self._execute_script_thread).start()

    def _execute_script_thread(self):
        try:
            # Get inputs from GUI
            script_path = ""
            env = os.environ.copy()

            if self.selected_action == "invite":
                script_path = "invite_to_job_cdp_human.py"
                env['START_URL'] = self.input_fields['start_url'].get()
                env['JOB_QUERY'] = self.input_fields['job_query'].get()
            elif self.selected_action == "favorites":
                script_path = "add_to_favorites.py"
                env['START_URL'] = self.input_fields['start_url'].get()
                env['FAVORITE_LIST_NAME'] = self.input_fields['favorite_list_name'].get()
            elif self.selected_action == "message":
                script_path = "message_talent.py"
                env['START_URL'] = self.input_fields['start_url'].get()
                env['MESSAGE'] = self.input_fields['message'].get("1.0", tk.END).strip()
                if 'job_query' in self.input_fields:
                    env['JOB_QUERY'] = self.input_fields['job_query'].get()

            # Ensure the CDP URL is always set
            env['DEBUG_URL'] = "http://127.0.0.1:9222"

            # Log the command and parameters
            self.update_console(f"[i] Starting script: {script_path}\n")
            self.update_console(f"[i] START_URL: {env.get('START_URL')}\n")
            if self.selected_action == "invite":
                self.update_console(f"[i] JOB_QUERY: {env.get('JOB_QUERY')}\n")
            elif self.selected_action == "favorites":
                self.update_console(f"[i] FAVORITE_LIST_NAME: {env.get('FAVORITE_LIST_NAME')}\n")
            elif self.selected_action == "message":
                self.update_console(f"[i] MESSAGE: {env.get('MESSAGE')}\n")
            
            # Run the script as a subprocess
            process = subprocess.Popen([sys.executable, script_path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)

            # Read and update the console in real-time
            for line in process.stdout:
                self.update_console(line)

            process.wait()
            self.update_console("[i] Script finished.\n")

        except FileNotFoundError:
            self.update_console(f"[x] Error: Could not find the script file '{script_path}'. Please make sure it is in the same directory as this application.\n")
        except Exception as e:
            self.update_console(f"[x] An unexpected error occurred: {e}\n")

    def update_console(self, text):
        self.console_text.config(state=tk.NORMAL)
        self.console_text.insert(tk.END, text)
        self.console_text.see(tk.END)
        self.console_text.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    app = VoicesAutomationApp(root)
    root.mainloop()