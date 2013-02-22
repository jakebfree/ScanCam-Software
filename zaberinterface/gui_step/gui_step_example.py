import sys, os
sys.path.append(os.path.abspath('../'))

try:
    import gobject
    import gtk
    import gtk.glade
except:
    print "You need to install pyGTK or GTKv2 ",
    print "or set your PYTHONPATH correctly."
    sys.exit(1)

from threading import Thread
import signal

from linear_slides import multiaxis_linear_slides, STEP
from serial_connection import serial_connection

class ThreadedMultiAxis(Thread):
    def __init__(self, connection, axes):
        Thread.__init__(self)

        self.connection = connection
        
        self.multiaxis_device = \
                multiaxis_linear_slides(connection, axes, 'foo', run_mode = STEP, verbose = True)
        
        # Will print out 'foo'
        print self.multiaxis_device.get_id()

        self.multiaxis_device.new_meta_command('stepped_sweep',(('move_relative',{'x':0.2}),\
                                                                ('pause',),\
                                                                ('repeat', 5)))
        
        self.multiaxis_device.new_meta_command('sweep_and_move',(('store_current_position', 0),\
                                                                 ('stepped_sweep',),\
                                                                 ('move_stored_position', 0),\
                                                                 ('move_relative',{'y':3.125e-1*64}),\
                                                                 ('pause',)))

        self.multiaxis_device.new_meta_command('multisweep', (('sweep_and_move',),\
                                                              ('repeat',4)))

        self.multiaxis_device.multisweep()        
        return None

    def run(self):
        self.connection.open()
        return None

class GuiStep:

    def __init__(self, connection):
        self.widgets = gtk.glade.XML('gui_step.glade', 'top_level_window')
        self.widgets.signal_autoconnect(self)

        self.connection = connection
        self.id = 'gui'

        self.connection.register(self.packet_handler, self.id)
        
        return None
    
    def gtkloop_packet_handler(self, packet):
        print packet
        return False

    def packet_handler(self, packet):
        gobject.idle_add(self.gtkloop_packet_handler, packet)
        return None

    def on_next_button_clicked(self, event):
        self.connection.packet_q.put(((self.id,'foo'),('step',)))
        return None
    
    def on_top_level_window_destroy(self, event):
        gtk.main_quit()
        return None

def run_gui_step(argv):
    
    gtk.gdk.threads_init()

    axes = {'x':1, 'y':2, 'z':3}
    io = serial_connection('/dev/ttyUSB0', '<2Bi')
    
    hardware = ThreadedMultiAxis(io, axes)
    gui_step = GuiStep(io)
    
    hardware.start()    

    try:
        gtk.main()
    except KeyboardInterrupt:
        gobject.idle_add(gtk.main_quit,())
    
    io.close()
    return None

if __name__ == "__main__":
    import sys
    run_gui_step(sys.argv)
