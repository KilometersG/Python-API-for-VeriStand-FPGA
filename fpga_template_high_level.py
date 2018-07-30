import fpga_config

configpath = input('Please enter the full filepath of your .fpgaconfig file: ')
vsfpga = fpga_config.VeriStandFPGA(configpath)
device = input('Please enter the device name of your FPGA as it appears in NI-MAX: ')
read_count = vsfpga.read_packets + 1
write_count = vsfpga.write_packets + 1

print('Please input five values separated by commas for the following channels')
print('Please enter PWMs as 0-100 Duty Cycles, Digital Lines as 1\'s or 0\'s and Analog Lines as floating points')
iteration_writes = {}
for i in range(1, write_count):
    poi = vsfpga.write_packet_list['packet{}'.format(i)]
    for j in range(poi.definition['channel_count']):
        valuestr = input('{}: '.format(poi.definition['name{}'.format(j)]))
        channel_values = valuestr.split(',')
        for k, value in enumerate(channel_values):
            iteration_writes['{},{}'.format(poi.definition['name{}'.format(j)],k)] = int(value)

loop_rate = input("Please enter desired FPGA loop rate in ms: ")
vsfpga.init_fpga(device, int(loop_rate))
vsfpga.start_fpga()

for i in range(5):
    vsfpga.vs_read_fifo(timeout=2000)
    print('Iteration {} values are: '.format(i))
    for j in range(1, read_count):
        poi = vsfpga.read_packet_list['packet{}'.format(j)]
        for k in range(poi.definition['channel_count']):
            channel_name = poi.definition['name{}'.format(k)]
            print('{}: {}'.format(channel_name, vsfpga.get_channel(channel_name)))
    for j in range(1, write_count):
        poi = vsfpga.write_packet_list['packet{}'.format(j)]
        for k in range(poi.definition['channel_count']):
            vsfpga.set_channel(channel_name=poi.definition['name{}'.format(k)],
                               value=iteration_writes['{},{}'.format(poi.definition['name{}'.format(k)], i)])
    vsfpga.vs_write_fifo(timeout=2000)
vsfpga.stop_fpga()