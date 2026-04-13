import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('browser tools', () => {
  let mockClient;
  let mockReadFile;
  let mockWriteFile;
  let mockMkdir;
  let mockCopyFile;
  let mockUnlink;

  beforeEach(() => {
    vi.resetModules();
    mockClient = { callTool: vi.fn().mockResolvedValue({ content: [{ type: 'text', text: 'ok' }] }) };
    mockReadFile = vi.fn().mockRejectedValue(new Error('ENOENT'));
    mockWriteFile = vi.fn().mockResolvedValue(undefined);
    mockMkdir = vi.fn().mockResolvedValue(undefined);
    mockCopyFile = vi.fn().mockResolvedValue(undefined);
    mockUnlink = vi.fn().mockResolvedValue(undefined);
  });

  function setupMocks() {
    vi.doMock('fs/promises', () => ({
      readFile: mockReadFile,
      writeFile: mockWriteFile,
      mkdir: mockMkdir,
      copyFile: mockCopyFile,
      unlink: mockUnlink,
    }));
  }

  function buildContext(whitelistTools) {
    return {
      log: vi.fn(),
      playwright: {
        getClient: () => mockClient,
        getTools: () => [],
      },
      moduleConfigs: {
        core: {
          playwright_tool_whitelist: whitelistTools.join(','),
          allowed_domains: 'example.com',
        },
      },
      isToolEnabled: () => true,
      artifactsDir: '/workspace/tmp',
    };
  }

  async function importAndRegister(whitelistTools) {
    setupMocks();
    const { register } = await import('../../modules/core/toolbox/browser.js');
    const handlers = {};
    const server = {
      tool: vi.fn((name, _desc, _schema, handler) => {
        handlers[name] = handler;
      }),
    };
    const context = buildContext(whitelistTools);
    register(server, context);
    return { handlers, server, context };
  }

  describe('browser_start_video', () => {
    it('forwards size params restructured into size object', async () => {
      const { handlers } = await importAndRegister(['browser_start_video']);

      await handlers.browser_start_video({
        user: 'a@b.com',
        width: 1280,
        height: 720,
      });

      expect(mockClient.callTool).toHaveBeenCalledWith({
        name: 'browser_start_video',
        arguments: { size: { width: 1280, height: 720 } },
      });
    });
  });

  describe('browser_stop_video', () => {
    it('parses video path, copies to runtime dir, cleans up source', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '- [Video](/tmp/pw-video/video.webm)' }],
      });

      const { handlers } = await importAndRegister(['browser_stop_video']);

      const result = await handlers.browser_stop_video({
        user: 'a@b.com',
        job_id: '42',
      });

      expect(mockMkdir).toHaveBeenCalledWith('/workspace/tmp/videos/42', { recursive: true });
      expect(mockCopyFile).toHaveBeenCalledWith(
        expect.stringContaining('/tmp/pw-video/video.webm'),
        expect.stringMatching(/^\/workspace\/tmp\/videos\/42\/\d+\.webm$/),
      );
      expect(mockUnlink).toHaveBeenCalled();
      expect(result.content[0].text).toMatch(/^Video saved to: \/workspace\/tmp\/videos\/42\/\d+\.webm$/);
    });

    it('uses custom filename when provided', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '- [Video](/tmp/pw-video/video.webm)' }],
      });

      const { handlers } = await importAndRegister(['browser_stop_video']);

      const result = await handlers.browser_stop_video({
        user: 'a@b.com',
        job_id: '42',
        filename: 'demo.webm',
      });

      expect(mockCopyFile).toHaveBeenCalledWith(
        expect.stringContaining('/tmp/pw-video/video.webm'),
        '/workspace/tmp/videos/42/demo.webm',
      );
      expect(result.content[0].text).toBe('Video saved to: /workspace/tmp/videos/42/demo.webm');
    });

    it('matches video links with dimensions in text (e.g. [Video 1280x720])', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '- [Video 1280x720](/tmp/pw/recording.webm)' }],
      });

      const { handlers } = await importAndRegister(['browser_stop_video']);

      const result = await handlers.browser_stop_video({
        user: 'a@b.com',
        filename: 'out.webm',
      });

      expect(mockCopyFile).toHaveBeenCalled();
      expect(result.content[0].text).toMatch(/Video saved to:/);
    });

    it('returns raw result when no video files in response', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: 'No recording active' }],
      });

      const { handlers } = await importAndRegister(['browser_stop_video']);

      const result = await handlers.browser_stop_video({
        user: 'a@b.com',
        job_id: '42',
      });

      expect(mockCopyFile).not.toHaveBeenCalled();
      expect(result).toEqual({
        content: [{ type: 'text', text: 'No recording active' }],
      });
    });
  });

  describe('playwright not connected', () => {
    it('returns error when client is null', async () => {
      mockClient = null;
      setupMocks();
      const { register } = await import('../../modules/core/toolbox/browser.js');
      const handlers = {};
      const server = {
        tool: vi.fn((name, _desc, _schema, handler) => {
          handlers[name] = handler;
        }),
      };
      const context = {
        log: vi.fn(),
        playwright: {
          getClient: () => null,
          getTools: () => [],
        },
        moduleConfigs: {
          core: {
            playwright_tool_whitelist: 'browser_snapshot',
            allowed_domains: 'example.com',
          },
        },
        isToolEnabled: () => true,
        artifactsDir: '/workspace/tmp',
      };
      register(server, context);

      const result = await handlers.browser_snapshot({ user: 'a@b.com' });

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain('Playwright MCP is not available');
    });
  });

  describe('healthcheck', () => {
    it('returns ok when playwright client is connected', async () => {
      setupMocks();
      const { healthcheck } = await import('../../modules/core/toolbox/browser.js');

      const results = await healthcheck({
        playwright: { getClient: () => mockClient },
      });

      expect(results).toEqual([{ tool: 'browser', status: 'ok', ms: 0 }]);
    });

    it('returns fail when playwright client is null', async () => {
      setupMocks();
      const { healthcheck } = await import('../../modules/core/toolbox/browser.js');

      const results = await healthcheck({
        playwright: { getClient: () => null },
      });

      expect(results).toEqual([{
        tool: 'browser',
        status: 'fail',
        error: 'Playwright MCP not connected',
      }]);
    });
  });
});
