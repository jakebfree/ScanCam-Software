from zaber_device import *


# Units are all with respect to 1 deg 
rotary_units = {
        'deg':                       1,
        'rad':                       (3.1416/180),
        }

class rotary_stage(zaber_device):
    ''' rotary_stage(connection, 
                 device_number,
                 id, 
                 deg_per_step = .000234375 * 64,   # default value for T-RS60A
                 units = 'deg',
                 run_mode = CONTINUOUS,
                 action_handler = None,
                 verbose = False):
    
    Modified zaber_device with support for more meaningful linear units.

    deg_per_step is the number of degrees the stage turns with one step


    See the documentation for zaber_device for the full usage.
    '''
    def __init__(self, 
                 connection, 
                 device_number, 
                 id = None,
                 deg_per_step = .000234375 * 64,   # datasheet microstep size times microsteps per step
                 units = 'deg',
                 run_mode = CONTINUOUS,
                 action_handler = None,
                 verbose = False):

        self.move_units = units
        
        zaber_device.__init__(self, connection, device_number, id = id,
                units_per_step = deg_per_step*rotary_units[self.move_units],
                run_mode = run_mode,
                action_handler = action_handler,
                verbose = verbose)
        


