// bsarch-native: the subset of BSArch's command line that AutoMod uses, on top of Ryan-rsm-McKenzie/bsa (TES4 family only).
//   bsarch pack <dir> <out.bsa> -sse|-tes5|-tes4|-fo3 [-z] [-mt]
//   bsarch unpack <archive> [<outdir>]     (no <outdir>: <archive folder>/<archive name without extension>)
// Exit code 1 and a message on stderr on any failure. -mt is accepted and ignored. A file directly in the pack folder is
// refused (an archive file needs a folder). Unpack refuses an entry whose path would leave <outdir>.
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

#include <binary_io/any_stream.hpp>
#include <binary_io/file_stream.hpp>
#include <bsa/tes4.hpp>

namespace fs = std::filesystem;
using namespace std::literals;
using bsa::tes4::archive_type;

static archive_type type_for(std::string ext)
{
	std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
	if (ext == ".nif" || ext == ".kf" || ext == ".hkx" || ext == ".btr" || ext == ".bto" || ext == ".btt") return archive_type::meshes;
	if (ext == ".dds") return archive_type::textures;
	if (ext == ".swf") return archive_type::menus;
	if (ext == ".xwm" || ext == ".wav") return archive_type::sounds;
	if (ext == ".fuz" || ext == ".lip") return archive_type::voices;
	if (ext == ".txt" || ext == ".hlsl") return archive_type::shaders;
	if (ext == ".tri") return archive_type::misc;
	if (ext == ".fnt") return archive_type::fonts;
	return archive_type::misc;
}

static void pack(const fs::path& in, const fs::path& out, bsa::tes4::version v, bool z)
{
	if (!fs::is_directory(in)) throw std::runtime_error("input is not a directory: " + in.string());
	bsa::tes4::archive a;
	auto flags = bsa::tes4::archive_flag::directory_strings | bsa::tes4::archive_flag::file_strings;
	if (z) flags |= bsa::tes4::archive_flag::compressed;
	a.archive_flags(flags);
	archive_type types = archive_type::none;
	std::size_t n = 0;
	for (const auto& e : fs::recursive_directory_iterator(in)) {
		if (!e.is_regular_file()) continue;
		const auto& p = e.path();
		const auto rel_dir = p.parent_path().lexically_relative(in).lexically_normal().generic_string();
		if (rel_dir.empty() || rel_dir == ".") throw std::runtime_error("file at archive root not supported: " + p.string());
		bsa::tes4::file f;
		f.read(p, { .version_ = v, .compression_type_ = z ? bsa::compression_type::compressed : bsa::compression_type::decompressed });
		auto it = a.find(rel_dir);
		if (it == a.end()) { a.insert(rel_dir, bsa::tes4::directory()); }
		auto d = a[rel_dir];
		d->insert(p.filename().generic_string(), std::move(f));
		types |= type_for(p.extension().string());
		++n;
	}
	if (n == 0) throw std::runtime_error("no files to pack");
	a.archive_types(types);
	a.write(out, v);
}

// The entry path joined under out, or an error when it is empty, absolute, names a drive, or has a ".." part: an archive
// from a third-party mod must not write outside the folder the caller chose.
static fs::path safe_join(const fs::path& out, const std::string& rel)
{
	if (rel.empty() || rel.front() == '/' || rel.find(':') != std::string::npos)
		throw std::runtime_error("unsafe path in archive: " + rel);
	std::size_t start = 0;
	while (start <= rel.size()) {
		auto end = rel.find('/', start);
		if (end == std::string::npos) end = rel.size();
		const auto part = rel.substr(start, end - start);
		if (part == "..") throw std::runtime_error("unsafe path in archive: " + rel);
		start = end + 1;
	}
	return out / rel;
}

static void unpack(const fs::path& in, const fs::path& out)
{
	bsa::tes4::archive a;
	const auto v = a.read(in);
	for (auto& d : a) {
		for (auto& f : d.second) {
			std::string rel = std::string(d.first.name()) + "/" + std::string(f.first.name());
			for (auto& c : rel) if (c == '\\') c = '/';
			const auto path = safe_join(out, rel);
			fs::create_directories(path.parent_path());
			binary_io::any_ostream os{ std::in_place_type<binary_io::file_ostream>, path };
			f.second.write(os, { .version_ = v });
		}
	}
}

int main(int argc, char** argv)
{
	try {
		std::vector<std::string_view> a(argv + 1, argv + argc);
		if (a.size() < 2) throw std::runtime_error("usage: bsarch pack <dir> <out> -sse|-tes5 [-z] [-mt] | unpack <archive> [<outdir>]");
		if (a[0] == "pack"sv) {
			if (a.size() < 3) throw std::runtime_error("pack needs <dir> <out>");
			bool z = false, haveV = false;
			bsa::tes4::version v{};
			for (std::size_t i = 3; i < a.size(); ++i) {
				if (a[i] == "-sse"sv) { v = bsa::tes4::version::sse; haveV = true; }
				else if (a[i] == "-tes5"sv) { v = bsa::tes4::version::tes5; haveV = true; }
				else if (a[i] == "-tes4"sv) { v = bsa::tes4::version::tes4; haveV = true; }
				else if (a[i] == "-fo3"sv) { v = bsa::tes4::version::fo3; haveV = true; }
				else if (a[i] == "-z"sv) z = true;
				else if (a[i] == "-mt"sv) { /* accepted; this shim is single-threaded */ }
				else throw std::runtime_error("unknown option: " + std::string(a[i]));
			}
			if (!haveV) throw std::runtime_error("missing game flag");
			pack(std::string(a[1]), std::string(a[2]), v, z);
		} else if (a[0] == "unpack"sv) {
			fs::path in{ std::string(a[1]) };
			fs::path out = a.size() > 2 ? fs::path{ std::string(a[2]) } : in.parent_path() / in.stem();
			unpack(in, out);
		} else throw std::runtime_error("unknown command: " + std::string(a[0]));
		return EXIT_SUCCESS;
	} catch (const std::exception& e) {
		std::cerr << "bsarch: error: " << e.what() << '\n';
		return EXIT_FAILURE;
	}
}
