import fpga_config
from nifpga import Session
import ntpath

configpath = input('Please enter the full filepath of your .fpgaconfig file: ')
vsfpga = fpga_config.config(configpath)
folder = ntpath.split(configpath)
full_bitpath = folder[0] + '\\{}'.format(vsfpga.bitfile)
read_count = vsfpga.read_packets + 1
write_count = vsfpga.write_packets + 1
read_packets = {}
write_packets = {}

for i in range(1, read_count):
    read_packets['packet{}'.format(i)] = vsfpga.create_packet('read', i)

for i in range(1, write_count):
    write_packets['packet{}'.format(i)] = vsfpga.create_packet('write', i)

print('Please input five values separated by commas for the following channels')
print('Please enter PWMs as 0-100 Duty Cycles, Digital Lines as 1\'s or 0\'s and Analog Lines as floating points')
write_values = {}
for i in range(1, write_count):
    write_packet = write_packets['packet{}'.format(i)]
    iteration_writes = {}
    for j in range(write_packet.definition['channel_count']):
        valuestr = input('{}: '.format(write_packet.definition['name{}'.format(j)]))
        channel_values = valuestr.split(',')
        for k, value in enumerate(channel_values):
            iteration_writes['{},{}'.format(write_packet.definition['name{}'.format(j)], k)] = value
    write_values['packet{}'.format(i)] = iteration_writes

device = input('Please input the name of your FPGA board as it appears in NI-MAX: ')
with Session(full_bitpath, device) as sesh:

    read_fifo = sesh.fifos['DMA_READ']
    write_fifo = sesh.fifos['DMA_WRITE']
    loop_timer = sesh.registers['Loop Rate (usec)']
    start = sesh.registers['Start']
    rtsi = sesh.registers['Write to  RTSI']
    ex_timing = sesh.registers['Use External Timing']
    irq = sesh.registers['Generate IRQ']

    loop_timer.write(1000)
    rtsi.write(False)
    ex_timing.write(False)
    irq.write(False)
    start.write(True)
    packed_reads = {}
    for i in range(5):
        packed_reads["iteration{}".format(i)] = read_fifo.read(number_of_elements=vsfpga.read_packets, timeout_ms=2000)
        write_list = []
        for j in range(1, write_count):
            poi = write_packets['packet{}'.format(j)]
            p_values = []
            this_iteration = write_values['packet{}'.format(j)]
            for k in range(poi.definition['channel_count']):
                channel_name = poi.definition['name{}'.format(k)]
                p_values.append(this_iteration['{},{}'.format(channel_name, i)])
            packed_data = poi.pack(p_values)
            write_list.append(packed_data)
        write_fifo.write(data=write_list, timeout_ms=2000)

    for i in range(5):
        print("Iteration {} Reads:".format(i+1))
        read_tup = packed_reads['iteration{}'.format(i)]
        current_it = read_tup[0]
        for j, u64 in enumerate(current_it):
            poi = read_packets['packet{}'.format(j+1)]
            print(poi.unpack(u64))

# Assumptions:
#   Bitfile in the same folder as the .fpgaconfig file
#   .fpgaconfig file follows the VeriStand standard
#   Bitfile is written with the VeriStand FPGA project template in LabVIEW
#       Control names and FIFO names have not been edited from the template names
#   The FPGA bitfile was generated using the VeriStand FPGA Suppport VIs for all IO.
#       Basic IO palette
#       Digital Lines not Ports
#       Pulse Measurement VI
#       Pulse Generation VI
#       Analog IO is FXP not integer
# Known Issues
#   FXP Unpack reports incorrect values
#   Adding error handling in general
#
