//###########################################################################
// Generic EDF save file decrypter tool.
// Credit to decord user Quarri6343 for figuring out what it used and for throwing together the basic use case, which I adapted for this program.
//###########################################################################

#include <iostream>
#include <fstream>
#include <iomanip>
#include <string>
#include <filesystem>

//CryptoPP
#include "cryptopp890/modes.h"
#include "cryptopp890/aes.h"
#include "cryptopp890/filters.h"
#include "cryptopp890/hex.h"
#include "cryptopp890/cryptlib.h"
#include "cryptopp890/secblock.h"
#include "cryptopp890/md5.h"
#include "cryptopp890/crc.h"

//Function to easy generate a string type output from input, key and iv data.
std::string aes_ctr_mode_decrypt( std::string& cipher, CryptoPP::SecByteBlock key, CryptoPP::byte* iv )
{
    std::string output;

    try
    {
        CryptoPP::CTR_Mode<CryptoPP::AES>::Decryption d( key, key.size(), iv );
        CryptoPP::StringSource( cipher, true,
            new CryptoPP::StreamTransformationFilter( d,
                new CryptoPP::StringSink( output )
            ) //StreamTransformationFilter
        ); //StringSource
    }
    catch( CryptoPP::Exception& exception )
    {
        std::cerr << exception.what() << std::endl;
        exit( 1 );
    }
    return output;
}

std::string aes_ctr_mode_encrypt( std::string& cipher, CryptoPP::SecByteBlock key, CryptoPP::byte* iv )
{
    std::string output;

    try
    {
        CryptoPP::CTR_Mode<CryptoPP::AES>::Encryption d( key, key.size(), iv );
        CryptoPP::StringSource( cipher, true,
            new CryptoPP::StreamTransformationFilter( d,
                new CryptoPP::StringSink( output )
            ) //StreamTransformationFilter
        ); //StringSource
    }
    catch( CryptoPP::Exception& exception )
    {
        std::cerr << exception.what() << std::endl;
        exit( 1 );
    }
    return output;
}

//Old algorithm, likely depreciated, as using CryptoPP itself works.
uint32_t calculate_crc32c_from_offset( uint8_t* data, uint64_t length, uint32_t* crc, uint64_t offset )
{
    data += offset;

    while( ((uintptr_t) data & 3) != 0 && length > 0 )
    {
        *crc = _mm_crc32_u8( *crc, *data++ );
        length--;
    }

    while( length >= 4 )
    {
        *crc = _mm_crc32_u32( *crc, *(uint32_t*) data );
        data += 4;
        length -= 4;
    }

    while( length > 0 )
    {
        *crc = _mm_crc32_u8( *crc, *data++ );
        length--;
    }

    return *crc;
}

void GenerateKeyBytes( CryptoPP::byte *keyByte, CryptoPP::byte* iv, std::wstring strn1, std::wstring strn2 )
{
    //Generate part 1
    CryptoPP::Weak1::MD5 md5;
    CryptoPP::byte digest[16];
    md5.CalculateDigest( digest, (CryptoPP::byte*) strn1.c_str(), strn1.length() * sizeof( wchar_t ) );

    memcpy( keyByte, digest, 16 );

    std::string code = "Edf5.*_Steam_Ver"; //This is the second half.
    memcpy( keyByte + 16, code.c_str() , 16 );

    //Generate part 2
    md5.CalculateDigest( digest, (CryptoPP::byte*) strn2.c_str(), strn2.length() * sizeof( wchar_t ) );
    memcpy( iv, digest, 16 );
}

//General EDF6 decode
void DecodeEDF6()
{
    CryptoPP::byte keyByte[32];
    CryptoPP::byte iv[CryptoPP::AES::BLOCKSIZE];

    //Check if folder exists,
    if( std::filesystem::is_directory( "./EDF6_Encrypted" ) )
    {
        std::cout << "EDF 6 Save files: Input directory found. Decrypting all files." << std::endl;
        int num_files = 0;

        //Decode all files in folder
        for( const auto& directory_entry : std::filesystem::directory_iterator( "./EDF6_Encrypted" ) )
        {
            if( directory_entry.is_regular_file() )
            {
                if( std::filesystem::is_directory( "./EDF6_Decrypted" ) )
                {
                    std::cout << directory_entry.path().filename() << std::endl;
                    std::wstring fileName = directory_entry.path().filename().wstring();

                    std::wstring proccessed_string_1 = L"edf6" + fileName + L".sav";
                    std::wstring proccessed_string_2 = L"edf6" + fileName + L".stm";

                    GenerateKeyBytes( keyByte, iv, proccessed_string_1.c_str(), proccessed_string_2.c_str() );

                    //read file
                    std::ifstream inputFile( directory_entry.path(), std::ios::binary );
                    std::string input_data( (std::istreambuf_iterator<char>( inputFile )), std::istreambuf_iterator<char>() );
                    inputFile.close();

                    //decode
                    std::string decodedFile;

                    CryptoPP::SecByteBlock key( keyByte, 32 );
                    decodedFile = aes_ctr_mode_decrypt( input_data, key, iv );

                    //Check magic.
                    if( decodedFile.substr( 0, 3 ) == "MDB" )
                        std::cout << "MDB header found, likely succeeded." << std::endl;

                    //Write.
                    std::ofstream outputFile( L"./EDF6_Decrypted/" + fileName, std::ios::binary );
                    outputFile.write( decodedFile.data(), decodedFile.size() );
                    outputFile.close();

                    num_files++;
                }
                else
                {
                    std::cout << "No valid output directory. Please create a EDF6_Decrypted folder." << std::endl;
                    break;
                }
            }
        }

        std::cout << "EDF 6 Save files: Proccessed " + std::to_string( num_files ) + " files." << std::endl;
    }
}

//General EDF5 decode
void DecodeEDF5()
{
    CryptoPP::byte keyByte[32];
    CryptoPP::byte iv[CryptoPP::AES::BLOCKSIZE];

    //Check if folder exists,
    if( std::filesystem::is_directory( "./EDF5_Encrypted" ) )
    {
        std::cout << "EDF 5 Save files: Input directory found. Decrypting all files." << std::endl;
        int num_files = 0;

        //Decode all files in folder
        for( const auto& directory_entry : std::filesystem::directory_iterator( "./EDF5_Encrypted" ) )
        {
            if( directory_entry.is_regular_file() )
            {
                if( std::filesystem::is_directory( "./EDF5_Decrypted" ) )
                {
                    std::cout << directory_entry.path().filename() << std::endl;
                    std::wstring fileName = directory_entry.path().filename().wstring();

                    std::wstring proccessed_string_1 = L"edf5" + fileName + L".sav";
                    std::wstring proccessed_string_2 = L"edf5" + fileName + L".stm";

                    GenerateKeyBytes( keyByte, iv, proccessed_string_1.c_str(), proccessed_string_2.c_str() );

                    //read file
                    std::ifstream inputFile( directory_entry.path(), std::ios::binary );
                    std::string input_data( (std::istreambuf_iterator<char>( inputFile )), std::istreambuf_iterator<char>() );
                    inputFile.close();

                    //decode
                    std::string decodedFile;

                    CryptoPP::SecByteBlock key( keyByte, 32 );
                    decodedFile = aes_ctr_mode_decrypt( input_data, key, iv );

                    //Check magic.
                    if( decodedFile.substr( 0, 3 ) == "MDB" )
                        std::cout << "MDB header found, likely succeeded." << std::endl;

                    //Write.
                    std::ofstream outputFile( L"./EDF5_Decrypted/" + fileName, std::ios::binary );
                    outputFile.write( decodedFile.data(), decodedFile.size() );
                    outputFile.close();

                    num_files++;
                }
                else
                {
                    std::cout << "No valid output directory. Please create a EDF5_Decrypted folder." << std::endl;
                    break;
                }
            }
        }

        std::cout << "EDF 5 Save files: Proccessed " + std::to_string( num_files ) + " files." << std::endl;
    }
}


//General EDF6 encode
void EncodeEDF6()
{
    CryptoPP::byte keyByte[32];
    CryptoPP::byte iv[CryptoPP::AES::BLOCKSIZE];

    //Check if folder exists,
    if( std::filesystem::is_directory( "./EDF6_Decrypted" ) )
    {
        std::cout << "EDF 6 Save files: Input directory found. Decrypting all files." << std::endl;
        int num_files = 0;

        //Decode all files in folder
        for( const auto& directory_entry : std::filesystem::directory_iterator( "./EDF6_Decrypted" ) )
        {
            if( directory_entry.is_regular_file() )
            {
                if( std::filesystem::is_directory( "./EDF6_Encrypted" ) )
                {
                    std::cout << directory_entry.path().filename() << std::endl;
                    std::wstring fileName = directory_entry.path().filename().wstring();

                    std::wstring proccessed_string_1 = L"edf6" + fileName + L".sav";
                    std::wstring proccessed_string_2 = L"edf6" + fileName + L".stm";

                    GenerateKeyBytes( keyByte, iv, proccessed_string_1.c_str(), proccessed_string_2.c_str() );

                    //read file
                    std::ifstream inputFile( directory_entry.path(), std::ios::binary );
                    std::string input_data( (std::istreambuf_iterator<char>( inputFile )), std::istreambuf_iterator<char>() );
                    inputFile.close();

                    int checksum = 0;
                    memcpy( &checksum, input_data.data() + 0xc, 4 );

                    //generate checksum
                    CryptoPP::byte chk[4];
                    CryptoPP::CRC32C checksum_gen;
                    checksum_gen.Update( (CryptoPP::byte*) input_data.data() + 0x14, input_data.size() - 0x14 );
                    checksum_gen.TruncatedFinal( chk, 4 );

                    int computed_checksum = 0;
                    memcpy( &computed_checksum, chk, 4 );

                    computed_checksum = ~computed_checksum;

                    std::cout << "ORIGINAL: 0x" << std::hex << checksum << std::endl;
                    std::cout << "CRC32C result2: " << std::hex << computed_checksum << std::endl;

                    memcpy( input_data.data() + 0xc, &computed_checksum, 4 );

                    //encode
                    std::string encodedFile;

                    CryptoPP::SecByteBlock key( keyByte, 32 );
                    encodedFile = aes_ctr_mode_encrypt( input_data, key, iv );

                    //Check magic.
                    if( encodedFile.substr( 0, 3 ) == "MDB" )
                        std::cout << "MDB header found, likely succeeded." << std::endl;

                    //Write.
                    std::ofstream outputFile( L"./EDF6_Encrypted/" + fileName, std::ios::binary );
                    outputFile.write( encodedFile.data(), encodedFile.size() );
                    outputFile.close();

                    num_files++;
                }
                else
                {
                    std::cout << "No valid output directory. Please create a EDF6_Decrypted folder." << std::endl;
                    break;
                }
            }
        }

        std::cout << "EDF 6 Save files: Proccessed " + std::to_string( num_files ) + " files." << std::endl;
    }
}

/*
void EncodeEDF6()
{
    CryptoPP::byte keyByte[32];
    CryptoPP::byte iv[CryptoPP::AES::BLOCKSIZE];

    GenerateKeyBytes( keyByte, iv, L"edf6MAIN.GST.sav", L"edf6MAIN.GST.stm" );
    CryptoPP::SecByteBlock key( keyByte, 32 );

    // Read ciphertext from file
    std::ifstream inputFile( "IN.bin", std::ios::binary );
    std::string ciphertext( (std::istreambuf_iterator<char>( inputFile )), std::istreambuf_iterator<char>() );
    inputFile.close();

    //generate checksum
    CryptoPP::byte chk[4];
    CryptoPP::CRC32C checksum_gen;
    checksum_gen.CalculateDigest( chk, (CryptoPP::byte*) ciphertext.data() + 0xf, ciphertext.size() );

    memcpy( &ciphertext[0xc], chk, 4);

    std::string encrypted;
    encrypted = aes_ctr_mode_encrypt( ciphertext, key, iv );

    // Write encrypted text to file
    std::ofstream outputFile( "OUT.bin", std::ios::binary );
    outputFile.write( encrypted.data(), encrypted.size() );
    outputFile.close();

    //std::ofstream outputFile2( "checksumTest.bin", std::ios::binary );
    //outputFile2.write( ciphertext.data(), ciphertext.size() );
    //outputFile2.close();

    //std::cout << "Decryption completed and saved" << std::endl;
}
*/

int main()
{
    //CryptoPP::byte keyByte[32];
    //CryptoPP::byte iv[CryptoPP::AES::BLOCKSIZE];

    //decode
    //DecodeEDF6();
    //DecodeEDF5();

    //encode
    //EncodeEDF6();

    std::cout << "Operation mode: encode(e) or decode(d)\n";

    std::string text;
    std::cin >> text;

    std::cout << "\n";

    if( text == "e" || text == "encode" )
    {
        EncodeEDF6();
    }
    else if( text == "d" || text == "decode" )
    {
        DecodeEDF6();
    }
    else
    {
        std::cout << "Invalid Operation\n";
    }

    //Undone, single file proccessing.

    system( "pause" );

    /*
    GenerateKeyBytes( keyByte, iv, L"edf5MAIN.GST.sav", L"edf5MAIN.GST.stm" );
    CryptoPP::SecByteBlock key( keyByte, 32 );

    // Read ciphertext from file
    std::ifstream inputFile( "MAIN_EDF5.GST", std::ios::binary );
    std::string ciphertext( (std::istreambuf_iterator<char>( inputFile )), std::istreambuf_iterator<char>() );
    inputFile.close();

    std::string recovered;
    recovered = aes_ctr_mode_decrypt( ciphertext, key, iv );

    int checksum = 0;
    memcpy( &checksum, recovered.data() + 0xc, 4 );

    //checksum part
    uint32_t crc = 0xFFFFFFFFu;
    uint64_t offset = 32;
    uint32_t result_crc = calculate_crc32c_from_offset( (uint8_t *)recovered.data(), recovered.size() - offset, &crc, offset );

    CryptoPP::byte chk[4];
    CryptoPP::CRC32C checksum_gen;
    checksum_gen.CalculateDigest( chk, (CryptoPP::byte*)recovered.data() + 0xf, recovered.size() );

    std::cout << "ORIGINAL: 0x" << std::hex << checksum << std::endl;

    //memcpy( &checksum, chk, 4 );

    std::cout << "CRC32C result: 0x" << std::hex << result_crc << std::endl;
    std::cout << "CRC32C result2: 0x" << std::hex << checksum << std::endl;

    // Write decrypted text to file
    std::ofstream outputFile( "OUT.bin", std::ios::binary );
    outputFile.write( recovered.data(), recovered.size() );
    outputFile.close();

    //std::cout << "Decryption completed and saved" << std::endl;

    */

    return 0;
}