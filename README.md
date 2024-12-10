# ZehnnFlow
ZehnnFlow comes from the German word "Zehn", meaning ten, symbolizing simplicity, focus, and completion (e.g., a 10/10 productive day,some work done[1] or no work[0])
A versatile productivity suite designed to support individuals with ADHD and neurotypicals in achieving a focused and efficient workflow.

## Overview  
**ZehnnFlow** is a minimalist desktop application built with [pywebview](). It provides tools to minimize distractions and optimize productivity in a clutter-free environment.  

## Key Features  
- **Task Management**: Organize your day with a simple and intuitive to-do list.  
- **AI-Powered Assistance**: Engage with an intelligent chatbot utilizing Retrieval-Augmented Generation (RAG) on custom datasets, powered by Llama3 and llama_index ([ollama]()).  
- **Streamlined Email Client**: Check your inbox, draft messages, and send emails effortlessly in a clean, user-friendly interface.  

## Roadmap  
Planned improvements for future versions include:  
1. **Integrated Notes**: Seamless note-taking with automatic indexing into the chatbot’s dataset.  
2. **Music Player**: Lightweight music player powered by YouTube-dl for enhanced focus sessions.  
3. **Enhanced User Interface**: Improved aesthetics and usability.  
4. **Service Integrations**: Compatibility with platforms such as OneNote.  
5. **AI Audio Model Integration**: Incorporate AI-generated audio for text-to-speech improvement among neurodivergent folks.

## Current Challenges  
- The email client UI requires refinement.  
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

3. Configure environment variables by creating a `.env` file in the project directory:  
   - `GOOGLE_APP_PASSWORD`: Your Google app password for email. (Not your Regular Password,would be a 16 digit key)
   - `EMAIL_ADDRESS`: Your email address.  

4. Add custom datasets (e.g., PDFs) to the `datasets` directory. These will be indexed for chatbot interactions.  

5. Start the application:  
   ```bash
   python zehnnflow.py
   ```  

## Contribution  
We welcome contributions to enhance **ZehnnFlow**. Please submit a pull request or open an issue to propose improvements.  

## License  
**ZehnnFlow** is released under the MIT License. See `LICENSE` for details.  
