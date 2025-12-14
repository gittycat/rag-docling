<script lang="ts">
  let messages = $state([
    { role: 'assistant', content: 'Hello! How can I help you today?' }
  ]);
  let inputText = $state('');

  function sendMessage() {
    if (!inputText.trim()) return;

    messages.push({ role: 'user', content: inputText });
    // Simulate assistant response
    messages.push({ role: 'assistant', content: 'This is a placeholder response. Backend integration coming soon!' });
    inputText = '';
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }
</script>

<div class="flex flex-col h-[calc(100vh-140px)]">
  <div class="flex-1 overflow-y-auto p-4 space-y-4">
    {#each messages as message, index (index)}
      <div class="chat {message.role === 'user' ? 'chat-end' : 'chat-start'}">
        <div class="chat-image avatar placeholder">
          <div class="bg-neutral text-neutral-content w-10 rounded-full">
            <span>{message.role === 'user' ? 'U' : 'AI'}</span>
          </div>
        </div>
        <div class="chat-header">
          {message.role === 'user' ? 'You' : 'Assistant'}
        </div>
        <div class="chat-bubble {message.role === 'user' ? 'chat-bubble-primary' : 'chat-bubble-secondary'}">
          {message.content}
        </div>
      </div>
    {/each}
  </div>

  <div class="p-4 bg-base-200">
    <div class="join w-full">
      <input
        type="text"
        placeholder="Type your message..."
        class="input input-bordered join-item flex-1"
        bind:value={inputText}
        onkeydown={handleKeydown}
      />
      <button class="btn btn-primary join-item" onclick={sendMessage}>
        Send
      </button>
    </div>
  </div>
</div>
