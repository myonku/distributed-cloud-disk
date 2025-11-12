class OutboxService:
    def __init__(self):
        self.outbox = []

    def add_message(self, message):
        """Add a message to the outbox."""
        self.outbox.append(message)

    def get_messages(self):
        """Retrieve all messages from the outbox."""
        return self.outbox

    def clear_outbox(self):
        """Clear all messages from the outbox."""
        self.outbox.clear()