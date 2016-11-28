import threading
import subprocess
import Queue

from gi.repository import Gtk, Gdk

from terminatorlib.tmux import notifications
from terminatorlib.util import dbg

def esc(seq):
    return '\033{}'.format(seq)


KEY_MAPPINGS = {
    Gdk.KEY_BackSpace: '\b',
    Gdk.KEY_Tab: '\t',
    Gdk.KEY_Insert: esc('[2~'),
    Gdk.KEY_Delete: esc('[3~'),
    Gdk.KEY_Page_Up: esc('[5~'),
    Gdk.KEY_Page_Down: esc('[6~'),
    Gdk.KEY_Home: esc('OH'),
    Gdk.KEY_End: esc('OF'),
    Gdk.KEY_Up: esc('[A'),
    Gdk.KEY_Down: esc('[B'),
    Gdk.KEY_Right: esc('[C'),
    Gdk.KEY_Left: esc('[D'),
}
ARROW_KEYS = {
    Gdk.KEY_Up,
    Gdk.KEY_Down,
    Gdk.KEY_Left,
    Gdk.KEY_Right
}

# TODO: implement ssh connection using paramiko
class TmuxControl(object):

    def __init__(self, session_name, notifications_handler):
        self.session_name = session_name
        self.notifications_handler = notifications_handler
        self.tmux = None
        self.output = None
        self.input = None
        self.consumer = None
        self.width = None
        self.height = None
        self.remote = None
        self.requests = Queue.Queue()

    def reset(self):
        self.tmux = self.input = self.output = self.width = self.height = None

    def run_command(self, command, marker, cwd=None, orientation=None,
                    pane_id=None):
        if self.input:
            if orientation:
                self.split_window(cwd=cwd, orientation=orientation,
                                  pane_id=pane_id, command=command,
                                  marker=marker)
            else:
                self.new_window(cwd=cwd, command=command, marker=marker)
        else:
            self.new_session(cwd=cwd, command=command, marker=marker)

    def split_window(self, cwd, orientation, pane_id,
                     command=None, marker=''):
        orientation = '-h' if orientation == 'horizontal' else '-v'
        tmux_command = 'split-window {} -t {} -P -F "#D {}"'.format(
            orientation, pane_id, marker)
        # TODO (dank): fix (getting None for pid, e.g. /proc/None/cwd)
        # if cwd:
        #     tmux_command += ' -c "{}"'.format(cwd)
        if command:
            tmux_command += ' "{}"'.format(command)

        self._run_command(tmux_command,
                          callback=self.notifications_handler.pane_id_result)

    def new_window(self, cwd=None, command=None, marker=''):
        tmux_command = 'new-window -P -F "#D {}"'.format(marker)
        # TODO (dank): fix (getting None for pid, e.g. /proc/None/cwd)
        # if cwd:
        #     tmux_command += ' -c "{}"'.format(cwd)
        if command:
            tmux_command += ' "{}"'.format(command)

        self._run_command(tmux_command,
                          callback=self.notifications_handler.pane_id_result)

    def attach_session(self):
        # self.kill_server()
        popen_command = ['tmux', '-2', '-C', 'attach-session',
                         '-t', self.session_name]
        if self.remote:
            popen_command[:0] =  ['ssh', self.remote, '--']
        self.tmux = subprocess.Popen(popen_command,
                                 stdout=subprocess.PIPE,
                                 stdin=subprocess.PIPE)
        self.requests.put(notifications.noop)
        self.input = self.tmux.stdin
        self.output = self.tmux.stdout
        self.start_notifications_consumer()
        self.initial_layout()

    def new_session(self, cwd=None, command=None, marker=''):
        self.kill_server(self.remote)
        quote = "'" if self.remote else ""
        popen_command = ['tmux', '-2', '-C', 'new-session', '-s', self.session_name,
                '-P', '-F', '{}#D {}{}'.format(quote, marker, quote)]
        if self.remote:
            popen_command[:0] = ['ssh', self.remote, '--']
        elif cwd:
            popen_command += ['-c', cwd]
        if command:
            popen_command.append(command)
        self.tmux = subprocess.Popen(popen_command,
                                     stdout=subprocess.PIPE,
                                     stdin=subprocess.PIPE)
        with self.requests.mutex:
            self.requests.queue.clear()

        self.requests.put(self.notifications_handler.pane_id_result)
        self.input = self.tmux.stdin
        self.output = self.tmux.stdout
        self.start_notifications_consumer()

    def refresh_client(self, width, height):
        dbg('{}::{}: {}x{}'.format("TmuxControl", "refresh_client", width, height))
        self.width = width
        self.height = height
        self._run_command('refresh-client -C {},{}'.format(width, height))

    def garbage_collect_panes(self):
        self._run_command('list-panes -s -t {} -F "#D"'.format(
            self.session_name),
            callback=self.notifications_handler.garbage_collect_panes_result)

    def initial_layout(self):
        self._run_command(
            'list-windows -t {} -F "#{{window_layout}}"'
            .format(self.session_name),
            callback=self.notifications_handler.initial_layout_result)

    def initial_output(self, pane_id):
        self._run_command(
            'capture-pane -J -p -t {} -eC -S - -E -'.format(pane_id),
            callback=self.notifications_handler.initial_output_result_callback(
                pane_id))

    def toggle_zoom(self, pane_id):
        self._run_command('resize-pane -Z -t {}'.format(pane_id))

    def send_keypress(self, event, pane_id):
        keyval = event.keyval
        state = event.state

        if keyval in KEY_MAPPINGS:
            key = KEY_MAPPINGS[keyval]
            if keyval in ARROW_KEYS and state & Gdk.ModifierType.CONTROL_MASK:
                key = '{}1;5{}'.format(key[:2], key[2:])
        else:
            key = event.string

        if state & Gdk.ModifierType.MOD1_MASK:
            # Hack to have CTRL+SHIFT+Alt PageUp/PageDown/Home/End
            # work without these silly [... escaped characters
            if state & (Gdk.ModifierType.CONTROL_MASK |
                        Gdk.ModifierType.SHIFT_MASK):
                return
            else:
                key = esc(key)

        if key == ';':
            key = '\\;'

        self.send_content(key, pane_id)

    def send_content(self, content, pane_id):
        quote = '"' if "'" in content else "'"
        self._run_command("send-keys -t {} -l {}{}{}".format(
                pane_id, quote, content, quote))

    def _run_command(self, command, callback=None):
        if not self.input:
            dbg('No tmux connection. [command={}]'.format(command))
        else:
            self.input.write('{}\n'.format(command))
            callback = callback or notifications.noop
            self.requests.put(callback)

    @staticmethod
    def kill_server(remote):
        command = ['tmux', 'kill-server']
        if remote:
            command[:0] = ['ssh', remote, '--']
        subprocess.call(command)

    def start_notifications_consumer(self):
        self.consumer = threading.Thread(target=self.consume_notifications)
        self.consumer.daemon = True
        self.consumer.start()

    def consume_notifications(self):
        handler = self.notifications_handler
        while self.tmux.poll() is None:
            line = self.output.readline()[:-1]
            if not line:
                continue
            line = line[1:].split(' ')
            marker = line[0]
            line = line[1:]
            notification = notifications.notifications_mappings[marker]()
            notification.consume(line, self.output)
            handler.handle(notification)
        handler.terminate()
