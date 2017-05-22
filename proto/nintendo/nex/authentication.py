
from proto.nintendo.nex.service import ServiceClient
from proto.nintendo.nex.stream import NexStreamOut
from proto.nintendo.nex.common import NexEncoder, NexData, DataHolder, StationUrl, DateTime
from proto.nintendo.nex.kerberos import KerberosEncryption, Ticket
import hashlib
import struct

import logging
logger = logging.getLogger(__name__)


class AuthenticationInfo(NexEncoder):
	version_map = {
		30400: -1,
		30504: 0,
		30810: 0
	}
	
	#As nex versions increase, these values increase as well
	nex_versions = {
		30400: 3,
		30504: 2002,
		30810: 3017
	}
	
	def __init__(self, token):
		self.token = token
		
	def get_name(self):
		return "AuthenticationInfo"
		
	def encode(self, stream):
		NexData().encode(stream)
		super().encode(stream)
		
	def encode_old(self, stream):
		stream.string(self.token)
		stream.u32(3)
		stream.u8(1)
		stream.u32(self.nex_versions[stream.version])
		
	encode_v0 = encode_old
	
	
class ConnectionData(NexEncoder):
	version_map = {
		30400: -1,
		30504: 1,
		30810: 1
	}
	
	def decode_old(self, stream):
		self.main_station = StationUrl(stream.string())
		self.unk_list = stream.list(stream.u8)
		self.unk_station = StationUrl(stream.string())
		
	def decode_v1(self, stream):
		self.decode_old(stream)
		self.server_time = DateTime(stream.u64())


class AuthenticationClient(ServiceClient):
	
	METHOD_LOGIN = 1
	METHOD_LOGIN_EX = 2
	METHOD_REQUEST_TICKET = 3
	METHOD_GET_PID = 4
	METHOD_GET_NAME = 5
	METHOD_LOGIN_WITH_CONTEXT = 6
	
	PROTOCOL_ID = 0xA
		
	def login(self, username, password):
		logger.info("Authentication.login(%s, %s)", username, password)
		#--- request ---
		stream, call_id = self.init_message(self.PROTOCOL_ID, self.METHOD_LOGIN)
		stream.string(username)
		self.send_message(stream)
		
		#--- response ---
		self.handle_login_result(call_id, password)
		
	def login_ex(self, username, password, token):
		logger.info("Authentication.login_ex(%s, %s, %s)", username, password, token)
		#--- request ---
		stream, call_id = self.init_message(self.PROTOCOL_ID, self.METHOD_LOGIN_EX)
		stream.string(username)
		DataHolder(AuthenticationInfo(token)).encode(stream)
		self.send_message(stream)
		
		#--- response ---
		self.handle_login_result(call_id, password)
		
	def handle_login_result(self, call_id, password):
		stream = self.get_response(call_id)
		result = stream.u32()
		self.user_id = stream.u32()
		kerberos_data = stream.read(stream.u32()) #Used to validate kerberos key
		self.secure_station = ConnectionData.from_stream(stream).main_station
		server_name = stream.string()
		
		kerberos_key = password.encode("ascii")
		for i in range(65000 + self.user_id % 1024):
			kerberos_key = hashlib.md5(kerberos_key).digest()
		self.kerberos_encryption = KerberosEncryption(kerberos_key)
		
		logger.info("Authentication.login(_ex) -> (%08X, %s, %s)", self.user_id, self.secure_station, server_name)
		
	def request_ticket(self):
		logger.info("Authentication.request_ticket()")
		#--- request ---
		stream, call_id = self.init_message(self.PROTOCOL_ID, self.METHOD_REQUEST_TICKET)
		stream.u32(self.user_id)
		stream.u32(int(self.secure_station["PID"]))
		self.send_message(stream)
		
		#--- response ---
		stream = self.get_response(call_id)
		result = stream.u32()
		
		encrypted_ticket = stream.read(stream.u32())
		ticket_data = self.kerberos_encryption.decrypt(encrypted_ticket)
		ticket_key = ticket_data[:0x20]
		length = struct.unpack_from("I", ticket_data, 0x24)[0]
		ticket_buffer = ticket_data[0x28 : 0x28 + length]

		logger.info("Authentication.request_ticket -> %s", ticket_key.hex())
		return Ticket(ticket_key, ticket_buffer)
		
	def get_pid(self, name):
		logger.info("Authentication.get_pid(%s)", name)
		#--- request ---
		stream, call_id = self.init_message(self.PROTOCOL_ID, self.METHOD_GET_PID)
		stream.string(name)
		self.send_message(stream)
		
		#--- response ---
		stream = self.get_response(call_id)
		pid = stream.u32()
		logger.info("Authentication.get_pid -> %i", pid)
		return pid
		
	def get_name(self, id):
		logger.info("Authentication.get_name(%i)", id)
		#--- request ---
		stream, call_id = self.init_message(self.PROTOCOL_ID, self.METHOD_GET_NAME)
		stream.u32(id)
		self.send_message(stream)
		
		#--- response ---
		stream = self.get_response(call_id)
		name = stream.string()
		logger.info("Authentication.get_name -> %s", name)
		return name
		
	#-- login_with_context
