st.sidebar.markdown(
        """
        <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0 22px 0;">
            <svg width="48" height="48" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect width="100" height="100" rx="22" fill="url(#bg_grad)" />
                <circle cx="50" cy="50" r="38" stroke="url(#ring_grad)" stroke-width="3" stroke-dasharray="8 6" opacity="0.6"/>
                <path d="M40 30L72 50L40 70V30Z" fill="white" fill-opacity="0.95"/>
                <path d="M52 24L64 48L48 50L58 76L38 52L52 50L50 24Z" fill="#00F2FE"/>
                <defs>
                    <linearGradient id="bg_grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#1E1B4B" />
                        <stop offset="0.6" stop-color="#0F172A" />
                        <stop offset="1" stop-color="#020617" />
                    </linearGradient>
                    <linearGradient id="ring_grad" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
                        <stop stop-color="#00F2FE" />
                        <stop offset="1" stop-color="#6366F1" />
                    </linearGradient>
                </defs>
            </svg>
            <div style="line-height: 1.15;">
                <span style="font-size: 11px; font-weight: 700; color: #38BDF8; letter-spacing: 2px; text-transform: uppercase;">CENTRAL</span><br>
                <span style="font-size: 21px; font-weight: 900; color: #FFFFFF; letter-spacing: -0.5px;">DUBFY<span style="color: #6366F1;">AI</span></span>
                <span style="font-size: 13px; font-weight: 800; background: #00F2FE; color: #020617; padding: 2px 6px; border-radius: 4px; margin-left: 4px; vertical-align: middle;">VSL</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
