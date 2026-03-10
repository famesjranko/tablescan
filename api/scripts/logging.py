"""
Logging.py
    Written by: Andrew McDonald
    Initial: 31.08.21
    Updated: 23.10.21

    version: 1.2

Logic:
    Logging Class builds a log object that builds timestamped
    coloured string outputs for system logging
    
    INFO:       General system state information (service start/stop,
                configuration assumptions, system action
    DEBUG:      System diagnostic information for sysadmins, etc.
    WARNING:    Anything with potential to cause application oddities,
                but that automatically recovers or is expected behaviour. 
                Such as missing or duplicated data, etc.
    ERROR:      Any fatal operation. These errors will force user
                (administrator, or direct user) intervention.
    SUCCESS:    On successful completion of computational process/task
"""

import datetime as date


class Logging:

    INFO = "\033[1;36;48m"      #cyan
    DEBUG = "\033[1;34;48m"     #blue
    WARNING = "\033[1;33;48m"   #yellow
    ERROR = "\033[1;31;48m"     #red
    SUCCESS = "\033[1;32;48m"   #green
    END = "\033[1;37;0m"        #white

    def time_stamp(self) -> str:
        """
        builds the timestamp for system logging to match django's inbuilt logging timestamp

        Returns:
            str: system log timestamp
        """
        time_stamp = date.datetime.now()
        return "[" + time_stamp.strftime("%d/%b/%Y %X") + "]"

    def output(self, type: str, msg: str) -> None:
        """
        prints coloured log message with timestamp

        Args:
            type (str): [system message type]
            msg (str): [system message]
        """

        # determine the colour for the log message
        if type == "INFO":
            colour = self.INFO
        elif type == "DEBUG":
            colour = self.DEBUG
        elif type == "WARNING":
            colour = self.WARNING
        elif type == "ERROR":
            colour = self.ERROR
        elif type == "SUCCESS":
            colour = self.SUCCESS

        # build message with colouring and timestamp
        log_message = f'{self.time_stamp()} {colour}"[{type}] {msg}"{self.END}'

        # print log to console
        print(log_message)
        