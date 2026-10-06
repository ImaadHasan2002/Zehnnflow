# ZehnnFlow
ZehnnFlow comes from the German word "Zehn", meaning ten, symbolizing simplicity, focus, and completion (e.g., a 10/10 productive day,some work done[1] or no work[0])
A versatile productivity suite designed to support individuals in achieving a focused and efficient workflow.

## Overview  
**ZehnnFlow** is a minimalist desktop application built with [pywebview](). It provides tools to minimize distractions and optimize productivity in a clutter-free environment.  

## Key Features  
- **Task Management**: Organize your day with a simple and intuitive to-do list.  
- **AI-Powered Assistance**: Engage with an intelligent chatbot utilizing Retrieval-Augmented Generation (RAG) on custom datasets, powered by Llama3 and llama_index ([ollama]()).  
- **Streamlined Email Client**: Check your inbox, draft messages, and send emails effortlessly in a clean, user-friendly interface.  
- **Integrated Notes**: Save notes that are automatically indexed into the chatbot dataset.  
- **Focus Music + Timer**: Run focus sessions with YouTube, SoundCloud or Spotify ambient tracks and a built-in timer.  
- **Read-Aloud Chat**: Use accessibility controls to read AI responses aloud.  

## Roadmap  
Planned improvements for future versions include:  
1. [x] **Integrated Notes**: Seamless note-taking with automatic indexing into the chatbot dataset.  
2. [x] **Music Player**: Lightweight focus player with YouTube links and optional yt-dlp metadata enrichment.  
3. [x] **Enhanced User Interface**: Improved aesthetics and usability across all pages.  
4. [x] **Service Integrations**: Note import/export workflow for cross-tool usage (for example, OneNote markdown workflows).  
5. [x] **AI Audio Support**: Read-aloud controls for chat responses to support accessibility needs.

## Current Challenges  
- Streamlining the distribution process for easier installation.  
- Improving user accessibility by reducing dependencies on Python libraries.  

## System Requirements  
To run **ZehnnFlow**, ensure the following prerequisites are met:  
- **Python**: Version 3.10 or later.  
- **Required Libraries**: Listed in the `requirements.txt` file.  
- **Ollama**: Pre-installed with Llama3.  

## Installation and Setup  

Follow these steps to set up **ZehnnFlow**:  

1. Clone the repository:  
   ```bash
   git clone

2. Install the necessary dependencies:  
   ```bash
   pip install -r requirements.txt
   ```  

3. Configure environment variables by creating a `.env` file in the project directory (both lowercase and uppercase variants are supported):  
   - `google` or `GOOGLE_APP_PASSWORD`: Your Google app password for email (16-character app password).  
   - `email` or `EMAIL_ADDRESS`: Your email address.  

4. Add custom datasets (e.g., PDFs) to the `data` directory. These will be indexed for chatbot interactions.  
   - Notes you save in the app are also synced into `data/notes/` automatically (`notes.json` is the source of truth; stray files in `data/notes/` are removed on sync).
   - Only `.txt`, `.md` and `.pdf` files are indexed.

5. Start the application:  
   ```bash
   python zehnnflow.py                 # desktop window (pywebview)
   python zehnnflow.py --web           # plain web server on http://127.0.0.1:5000
   python zehnnflow.py --web --host 0.0.0.0 --port 8080
   ```  
   Startup only creates folders. PDF text extraction, note syncing and chat indexing happen on the first chat message, and the index is cached until the files in `data/` change.

   Optional settings: `ZEHNNFLOW_HOME` (where `data/`, `notes.json`, `tasks.json` live), `ZEHNNFLOW_LLM_MODEL` (default `llama3`), `ZEHNNFLOW_EMBED_MODEL`.

6. Run the tests:  
   ```bash
   pip install pytest && pytest
   ```  

## Contribution  
We welcome contributions to enhance **ZehnnFlow**. Please submit a pull request or open an issue to propose improvements.  

## License  
**ZehnnFlow** is released under the MIT License. See `LICENSE` for details.  
