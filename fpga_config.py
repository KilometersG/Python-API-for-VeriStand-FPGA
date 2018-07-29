import xml.etree.ElementTree as ET
from nifpga import Session
import ntpath

class VeriStandError(Exception):
    """
    Base class for exceptions in this API
    """
    pass

class ConfigError(VeriStandError):
    """
    Exception raised for errors in the .fpgaconfig file

    Attributes
        message = explanation of error.
    """
    def __init__(self, message):
        self.message = message

class PacketError(VeriStandError):
    """
    Exception raised for errors in a packet

    Attributes
        Message -- explanation of error
        packetID -- packet number and direction that the error occurred in.
    """
    def __init__(self, message, packetID):
        self.message = message
        self.packetID = packetID


class VeriStandFPGA(object):
    """
    DMA FIFO info pulled from an .fpgaconfig file
    config_file is the file name of the XML that defines this FIFO
    Direction is a string stating read or write. 

    """

    def __init__(self, filepath):
        """
        Create a fpga_config object. The filepath is the path to the bitfile you wish to interact with.
        This creates the fpga configuration with a number of read and write packets.
        :param filepath:
        """
        self.filepath = filepath
        self.tree = ET.parse(self.filepath)
        self.root = self.tree.getroot()
        self.read_packets = -1
        self.write_packets = -1
        self.session = False
        self.write_fifo = False
        self.read_fifo = False
        for child in self.root:
            if child.tag == 'DMA_Read':
                self.read_packets = int(child[0].text)
                self.read_fifo_tag = child
            elif child.tag == 'DMA_Write':
                self.write_packets = int(child[0].text)
                self.write_fifo_tag = child
            elif child.tag == 'Bitfile':
                self.bitfile = child.text
            else:
                continue
        self.folder = ntpath.split(self.filepath)
        self.full_bitpath = self.folder[0] + '\\{}'.format(self.bitfile)
        if self.read_packets == -1:
            raise ConfigError(message='No DMA_Read tag present')
        elif self.write_packets == -1:
            raise ConfigError(message='No DMA_Write tag present')
        self.read_packet_list = {}
        self.write_packet_list = {}
        self.channel_value_table = {}
        for i in range(1, self.read_packets + 1):
            self.read_packet_list['packet{}'.format(i)] = self.create_packet('read', i)
            for j in range(self.read_packet_list['packet{}'.format(i)].definition['channel_count']):
                self.channel_value_table[self.read_packet_list['packet{}'.format(i)].definition['name{}'.format(j)]] = 0
        for i in range(1, self.write_packets + 1):
            self.write_packet_list['packet{}'.format(i)] = self.create_packet('write', i)
            for j in range(self.write_packet_list['packet{}'.format(i)].definition['channel_count']):
                self.channel_value_table[self.write_packet_list['packet{}'.format(i)].definition['name{}'.format(j)]] = 0

    def init_fpga(self, device, loop_rate):
        self.session = Session(self.full_bitpath, device)
        self.write_fifo = self.session.fifos['DMA_WRITE']
        self.read_fifo = self.session.fifos['DMA_READ']
        self.loop_timer = self.session.registers['Loop Rate (usec)']
        self.fpga_start = self.session.registers['Start']
        self.fpga_rtsi = self.session.registers['Write to  RTSI']
        self.fpga_ex_timing = self.session.registers['Use External Timing']
        self.fpga_irq = self.session.registers['Generate IRQ']

        self.loop_timer.write(loop_rate)
        self.fpga_rtsi.write(False)
        self.fpga_ex_timing.write(False)
        self.fpga_irq.write(False)

    def start_fpga(self):
        self.fpga_start.write(True)

    def set_channel(self, channel_name, value):
        self.channel_value_table[channel_name] = value

    def get_channel(self, channel_name):
        return self.channel_value_table[channel_name]

    def vs_read_fifo(self, timeout):
        if self.read_fifo == False:
            raise ConfigError('Session not initialized. Please first call the VeriStandFPGA.init fpga method before reading')
        else:
            read_tup = self.read_fifo.read(number_of_elements=self.read_packets, timeout=timeout)
            data = read_tup[0]
            for i, u64 in enumerate(data):
                poi = self.read_packet_list['packet{}'.format(i+1)]
                read_vals = poi.unpack(u64)
                for key in read_vals:
                    self.channel_value_table[key] = read_vals[key]

    def vs_write_fifo(self, timeout):
        if self.write_fifo == False:
            raise ConfigError('Session not initialized. Please first call the VeriStandFPGA.init_fpga method before writing')
        else:
            write_list = []
            for i in range(1, self.write_packets + 1):
                poi = self.write_packet_list['packet{}'.format(i)]
                packet_vals = []
                for j in range(poi.definition['channel_count']):
                    packet_vals.append(self.channel_value_table[poi.definition['name{}'.format(j)]])
                write_list.append(poi.pack(packet_vals))
            self.write_fifo.write(data=write_list, timeout=timeout)

    def create_packet(self, direction, index):
        """

        :param direction:
        :param index:
        :return:
        """
        this_packet = Packet(self, direction, index)
        return this_packet


class Packet(object):
    def __init__(self, config, direction, index=1):
        """
        Generate an object that defines a packet in a DMA FIFO
        The object will have the following attributes: channel_count, name(0-x), description(0-x), and
        data_type(0-x)
        The packet indexes are 1 to N
        The channel indexes are 0 to N
        The difference in indexing is due to the VeriStand FPGA Config file standard
        :param config: the VeriStand FPGA Config object the packet is a part of
        :param direction: direction of the FIFO. This should be 'read' or 'write'.
        :param index: The index of the packet you wish to define. The value should be an integer of 1 or greater.
        :return: a dictionary with channel count, names, descriptions, and data types.
        """
        self.direction = direction
        self.index = index
        if self.direction.lower() == 'read':
            fifo = config.read_fifo_tag
        elif self.direction.lower() == 'write':
            fifo = config.write_fifo_tag
        else:
            raise BaseException('direction must be either read or write')

        packet_def = {}
        packet = fifo[self.index]
        packet_def['channel_count'] = packet.__len__()
        for i in range(packet_def['channel_count']):
            packet_def['name{}'.format(i)] = packet[i][0].text
            packet_def['data_type{}'.format(i)] = packet[i].tag
            if packet_def['data_type{}'.format(i)] == 'FXPI32':
                packet_def['FXPWL{}'.format(i)] = packet[i][5].text
                packet_def['FXPIWL{}'.format(i)] = packet[i][6].text
        self.definition = packet_def

    def unpack(self, data):
        """

        :param data: U64 value that comes out of the DMA_Read
        :return: real_values: dictionary of real_values with channel names as keys and unpacked channels as values
        """
        binstr = '{0:064b}'.format(int(data))
        real_values = {}
        for i in range(self.definition['channel_count']):
            if self.definition['data_type{}'.format(i)] == 'FXPI32':
                chnlunpck = 0
                chnldata = binstr[int(i*32):int((i+1)*32)]
                nopad = chnldata[32 - int(self.definition['FXPWL{}'.format(i)]):int((i + 1) * 32)]
                for index, char in enumerate(nopad):
                    if int(nopad[0]) != 0:
                       if int(char) == 0:
                           char = 1
                       else:
                            char = 0
                    powof = int(self.definition['FXPIWL{}'.format(i)]) - 1 - index
                    bitval = int(char) * 2 ** powof
                    chnlunpck = chnlunpck + bitval
                real_values['{}'.format(self.definition['name{}'.format(i)])] = chnlunpck

            elif self.definition['data_type{}'.format(i)] == 'PWM':
                lowtime = int(binstr[:32])
                hitime = int(binstr[32:])
                dutycycle = hitime/(hitime+lowtime)
                real_values['{}'.format(self.definition['name{}'.format(i)])] = dutycycle

            elif self.definition['data_type{}'.format(i)] == 'Boolean':
                bit = binstr[i]
                real_values['{}'.format(self.definition['name{}'.format(i)])] = bool(bit)

        return real_values

    def pack(self, real_values):
        """

        :param real_values: list of values to write to the channels in this packet
        :return packed_data: a U64 that represents the real values entered into this function
        """
        datastr = ''
        for i in range(self.definition['channel_count']):
            if self.definition['data_type{}'.format(i)] == 'Boolean':
                value = int(real_values[i])
                if value:
                    bit = 1
                else:
                    bit = 0
                datastr = datastr + (str(bit))

            elif self.definition['data_type{}'.format(i)] == 'PWM':
                dutycycle = int(real_values[0])
                hitime = dutycycle
                lowtime = 100-dutycycle
                datastr = '{0:032b}'.format(lowtime) + '{0:032b}'.format(hitime)

            elif self.definition['data_type{}'.format(i)] == 'FXPI32':
                binstr = '0'
                negstr = ''
                value = float(real_values[i])
                for j in range(int(self.definition['FXPWL{}'.format(i)])-1):
                    check = abs(value) - 2**(int(self.definition['FXPIWL{}'.format(i)])-2-j)
                    if check >= 0:
                        binstr = binstr + '1'
                        value = check
                    else:
                        binstr + binstr + '0'
                if int(real_values[i]) < 0:
                    for char in datastr:
                        if char == '0':
                            negstr = negstr + '1'
                        else:
                            negstr = negstr + '0'
                    binstr = negstr
                for j in range(32-int(self.definition['FXPWL{}'.format(i)])):
                    binstr = '0' + binstr
                datastr = datastr + binstr
        """
        Add padded 0's appropriately
        """
        packed_data = int(datastr, 2)
        return(packed_data)