#!/bin/env pyhton

"""
	Asynchronous Ping
	(c)2013 Mladen Vasic, mladen.vasic0@gmail.com

	- requires root/administrator privileges
"""
import gevent

import time, struct 
from gevent import socket, Timeout
from gevent.queue import Queue
from gevent.event import AsyncResult 
from gevent.pool import Pool

import logging
logging.basicConfig(level=logging.WARNING)

__all__ = ['asyncping']
__version__ = '0.1.0'

class ping(object):

	def __init__(self, queue, ttl=8, MAX_COUNTER=65535):
		self.queue = queue
		self.ttl = ttl
		self.MAX_COUNTER = MAX_COUNTER

		self.lookup_table = [None] * MAX_COUNTER
		self.counter = 0

		self.log = logging.getLogger("ping")
		
		self.socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
		
		self.__recv_greenlet = gevent.spawn(self.__recv)
		self.__run_greenlet = gevent.spawn(self.__run)

	def stop(self):
		self.__recv_greenlet.kill()
		self.__run_greenlet.kill()

	def __checksum(self, source_string):
		sum = 0
		countTo = (len(source_string) / 2) * 2
		count = 0
		while count < countTo:
			thisVal = ord(source_string[count + 1]) * 256 + ord(source_string[count])
			sum = sum + thisVal
			sum = sum & 0xffffffff
			count = count + 2

		if countTo < len(source_string):
			sum = sum + ord(source_string[len(source_string) - 1])
			sum = sum & 0xffffffff

		sum = (sum >> 16)  +  (sum & 0xffff)
		sum = sum + (sum >> 16)
		answer = ~sum
		answer = answer & 0xffff

		answer = answer >> 8 | (answer << 8 & 0xff00)

		return answer	

	def __run(self):
		"""
		Main loop which getting task from queue, send ping and make 
		greenlet to wait for response
		"""
		while True:
			destination, external_event = self.queue.get()

			if self.counter == self.MAX_COUNTER:
				# rotate data in lookup_table
				self.counter = 0
			else:
				self.counter += 1

			internal_event = AsyncResult()
			gevent.spawn(self.__wait_for_event, internal_event, external_event)
			# save internal_event in lookup_table
			self.lookup_table[self.counter] = internal_event

			self.__send(destination, self.counter)

	def __wait_for_event(self, event_in, event_out):
		"""
		Greenlet that wait for reponse for x seconds or timeout
		"""
		try:
			result = event_in.get(timeout=self.ttl)
			event_out.set(result)
		except:
			event_out.set(None)

	def __send(self, destination, id):
		"""
		Sending to socket
		"""
		checksum = 0
		
		header = struct.pack("bbHHh", 8, 0, checksum, id, 1)
		bytesInDouble = struct.calcsize("d")
		data = (192 - bytesInDouble) * "Q"
		data = struct.pack("d", time.time()) + data

		checksum = self.__checksum(header + data)
		
		header = struct.pack(
			"bbHHh", 8, 0, socket.htons(checksum), id, 1
		)
		packet = header + data

		try:		
			self.socket.sendto(packet, (destination, 0))	
		except Exception, e:
			self.log.error(repr(e))

	def __recv(self):
		"""
		Reciving from socket
		"""
		while True:
			recPacket, addr = self.socket.recvfrom(1024)
			timeReceived = time.time()
			icmpHeader = recPacket[20:28]
			type, code, checksum, packetID, sequence = struct.unpack(
				"bbHHh", icmpHeader
			)

			if type == 0:
				bytesInDouble = struct.calcsize("d")
				timeSent = struct.unpack("d", recPacket[28:28 + bytesInDouble])[0]

				try:
					# with recived packetID try to find internal_event in lookup_table 
					event = self.lookup_table[packetID]
					if event:
						event.set(timeReceived - timeSent)
						self.lookup_table[packetID] = None
				except Exception, e:
					self.log.error(repr(e))
			else:
				self.log.debug("packet not recognized from %s" % addr)

if __name__ == '__main__':
	logging.basicConfig(level=logging.DEBUG)

	def task(queue, destination, retries):
		"""
		Greenlet task
		"""
		result = False
		_retries = 0
		while not result and _retries < retries:
			event = AsyncResult()
			queue.put((destination, event))
			result = event.get()
			_retries += 1

		if result:
			print destination, result, _retries

	def iprange(start, end):
		"""
		IP range generator
		"""
		current = start
		parts = current.split(".")

		while current != end:
			yield current
						
			parts[3] = int(parts[3]) + 1

			increment = False
			for x in range(3,0,-1):
				if increment:
					parts[x] = int(parts[x]) + 1
					increment = False
				if (int(parts[x]) == 256):
					parts[x] = 0
					increment = True

			current = "%s.%s.%s.%s" % tuple(parts) 

	import argparse

	parser = argparse.ArgumentParser(description="Asynchronous PING")
	parser.add_argument('start', help="starting IP address")
	parser.add_argument('end', help="ending IP address")

	parser.add_argument('-r', '--retries', default=2, help="number of retries")
	parser.add_argument('-t', '--ttl', default=2, help="time to wait for answer in seconds")
	parser.add_argument('-p', '--pool', default=64, help="maximum number of greenlets")
	args = parser.parse_args()
	
	queue = Queue()
	p = ping(queue, ttl=int(args.ttl))
	pool = Pool(int(args.pool))

	for ip in iprange(args.start, args.end):
		pool.spawn(task, queue, ip, int(args.retries))

	pool.join()

	p.stop()
